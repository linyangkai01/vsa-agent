using System;
using System.Collections.Concurrent;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

public sealed class VsaRuntimeLogPump : IDisposable
{
    private const int QueueCapacity = 128;
    private const int ReadBufferChars = 4096;
    private const int MaxEntryChars = 8192;
    private static readonly object OutputGate = new object();
    private static readonly Encoding Utf8NoBom = new UTF8Encoding(false);
    private static readonly Regex Authorization = new Regex(
        @"(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex QuotedAuthorization = new Regex(
        @"([""']authorization[""']\s*:\s*[""'])(?:bearer\s+)?[^""']*([""'])",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex QuotedSecret = new Regex(
        @"([""'](?:api[-_]?key|access[-_]?token|token|password)[""']\s*:\s*[""'])[^""']*([""'])",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex Secret = new Regex(
        @"((?:api[-_]?key|access[-_]?token|token|password)\s*[:=]\s*)[^\s,;]+",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex DataImage = new Regex(
        @"data:image/[^;\s""']+;base64,[A-Za-z0-9+/=_\s-]*",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Singleline);
    private static readonly Regex QuotedImage = new Regex(
        @"([""'](?:image|image_url|input_image|b64_json)[""']\s*:\s*[""'])[A-Za-z0-9+/=_-]{64,}([""'])",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex Base64 = new Regex(
        @"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{64,}(?![A-Za-z0-9+/=_-])",
        RegexOptions.CultureInvariant);

    private sealed class Entry
    {
        internal readonly string Text;
        internal readonly bool IsError;

        internal Entry(string text, bool isError)
        {
            Text = text;
            IsError = isError;
        }
    }

    private readonly string _componentLogPath;
    private readonly string _stackLogPath;
    private readonly string _prefix;
    private readonly BlockingCollection<Entry> _entries;
    private readonly CancellationTokenSource _cancel;
    private readonly Task[] _readers;
    private readonly Task _consumer;
    private Exception _failure;
    private int _remainingReaders = 2;
    private int _completeStarted;
    private int _disposed;

    public VsaRuntimeLogPump(
        TextReader standardOutput,
        TextReader standardError,
        string componentLogPath,
        string stackLogPath,
        string prefix)
    {
        _componentLogPath = componentLogPath;
        _stackLogPath = stackLogPath;
        _prefix = prefix;
        _entries = new BlockingCollection<Entry>(
            new ConcurrentQueue<Entry>(), QueueCapacity);
        _cancel = new CancellationTokenSource();
        _consumer = StartLongRunning(Consume);
        _readers = new[]
        {
            StartLongRunning(delegate { ReadStream(standardOutput, false); }),
            StartLongRunning(delegate { ReadStream(standardError, true); })
        };
    }

    public static string ProtectText(string text)
    {
        string protectedText = text ?? String.Empty;
        protectedText = Authorization.Replace(protectedText, "${1}[REDACTED]");
        protectedText = QuotedAuthorization.Replace(protectedText, "${1}[REDACTED]${2}");
        protectedText = QuotedSecret.Replace(protectedText, "${1}[REDACTED]${2}");
        protectedText = Secret.Replace(protectedText, "${1}[REDACTED]");
        protectedText = DataImage.Replace(protectedText, "[REDACTED_IMAGE]");
        protectedText = QuotedImage.Replace(protectedText, "${1}[REDACTED_IMAGE]${2}");
        return Base64.Replace(protectedText, "[REDACTED_BASE64]");
    }

    public static void PublishProtected(
        string componentLogPath,
        string stackLogPath,
        string prefix,
        string protectedText,
        bool isError)
    {
        string text = protectedText ?? String.Empty;
        string line = prefix + " " + text;
        lock (OutputGate)
        {
            if (!String.IsNullOrWhiteSpace(componentLogPath))
            {
                File.AppendAllText(componentLogPath, text + Environment.NewLine, Utf8NoBom);
            }
            File.AppendAllText(stackLogPath, line + Environment.NewLine, Utf8NoBom);
            if (isError)
            {
                Console.Error.WriteLine(line);
            }
            else
            {
                Console.Out.WriteLine(line);
            }
        }
    }

    public void Complete(int timeoutMilliseconds)
    {
        if (timeoutMilliseconds <= 0)
        {
            throw new ArgumentOutOfRangeException("timeoutMilliseconds");
        }
        if (Interlocked.Exchange(ref _completeStarted, 1) != 0)
        {
            return;
        }

        DateTime deadline = DateTime.UtcNow.AddMilliseconds(timeoutMilliseconds);
        try
        {
            if (!Task.WaitAll(_readers, Remaining(deadline)))
            {
                throw new TimeoutException("Timed out draining process output readers");
            }
            if (!_consumer.Wait(Remaining(deadline)))
            {
                throw new TimeoutException("Timed out draining the process log queue");
            }
            if (_failure != null)
            {
                throw new IOException("Process log pump failed", _failure);
            }
        }
        catch (AggregateException error)
        {
            Exception cause = error.Flatten().InnerExceptions[0];
            throw new IOException("Process log pump failed", cause);
        }
        catch
        {
            _cancel.Cancel();
            TryCompleteAdding();
            throw;
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }
        _cancel.Cancel();
        TryCompleteAdding();
        _entries.Dispose();
        _cancel.Dispose();
    }

    private Task StartLongRunning(Action action)
    {
        return Task.Factory.StartNew(
            action,
            CancellationToken.None,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default);
    }

    private void ReadStream(TextReader reader, bool isError)
    {
        char[] buffer = new char[ReadBufferChars];
        StringBuilder entry = new StringBuilder(MaxEntryChars);
        bool previousWasCarriageReturn = false;
        try
        {
            int count;
            while ((count = reader.Read(buffer, 0, buffer.Length)) > 0)
            {
                for (int index = 0; index < count; index++)
                {
                    char value = buffer[index];
                    if (value == '\r')
                    {
                        Enqueue(entry.ToString(), isError);
                        entry.Length = 0;
                        previousWasCarriageReturn = true;
                    }
                    else if (value == '\n')
                    {
                        if (!previousWasCarriageReturn)
                        {
                            Enqueue(entry.ToString(), isError);
                            entry.Length = 0;
                        }
                        previousWasCarriageReturn = false;
                    }
                    else
                    {
                        previousWasCarriageReturn = false;
                        entry.Append(value);
                        if (entry.Length >= MaxEntryChars)
                        {
                            Enqueue(entry.ToString(), isError);
                            entry.Length = 0;
                        }
                    }
                }
            }
            if (entry.Length > 0)
            {
                Enqueue(entry.ToString(), isError);
            }
        }
        catch (OperationCanceledException)
        {
            if (!_cancel.IsCancellationRequested)
            {
                throw;
            }
        }
        catch (InvalidOperationException)
        {
            if (!_entries.IsAddingCompleted)
            {
                throw;
            }
        }
        catch (Exception error)
        {
            RecordFailure(error);
        }
        finally
        {
            if (Interlocked.Decrement(ref _remainingReaders) == 0)
            {
                TryCompleteAdding();
            }
        }
    }

    private void Enqueue(string text, bool isError)
    {
        _entries.Add(new Entry(text, isError), _cancel.Token);
    }

    private void Consume()
    {
        try
        {
            foreach (Entry entry in _entries.GetConsumingEnumerable(_cancel.Token))
            {
                PublishProtected(
                    _componentLogPath,
                    _stackLogPath,
                    _prefix,
                    ProtectText(entry.Text),
                    entry.IsError);
            }
        }
        catch (OperationCanceledException)
        {
            if (!_cancel.IsCancellationRequested)
            {
                throw;
            }
        }
        catch (Exception error)
        {
            RecordFailure(error);
        }
    }

    private void RecordFailure(Exception error)
    {
        Interlocked.CompareExchange(ref _failure, error, null);
        _cancel.Cancel();
        TryCompleteAdding();
    }

    private void TryCompleteAdding()
    {
        if (!_entries.IsAddingCompleted)
        {
            try
            {
                _entries.CompleteAdding();
            }
            catch (InvalidOperationException)
            {
            }
        }
    }

    private static int Remaining(DateTime deadline)
    {
        long remaining = (long)(deadline - DateTime.UtcNow).TotalMilliseconds;
        if (remaining <= 0)
        {
            return 0;
        }
        return remaining > Int32.MaxValue ? Int32.MaxValue : (int)remaining;
    }
}

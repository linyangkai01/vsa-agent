export function throttle<Args extends unknown[]>(
  callback: (...args: Args) => void,
  waitMs: number,
): (...args: Args) => void {
  let lastInvocationAt: number | undefined;
  let trailingTimer: ReturnType<typeof setTimeout> | undefined;
  let trailingArgs: Args | undefined;

  const invoke = (args: Args) => {
    lastInvocationAt = Date.now();
    callback(...args);
  };

  return (...args: Args) => {
    const elapsed = lastInvocationAt === undefined ? waitMs : Date.now() - lastInvocationAt;
    if (elapsed >= waitMs && trailingTimer === undefined) {
      invoke(args);
      return;
    }

    trailingArgs = args;
    if (trailingTimer !== undefined) {
      return;
    }

    trailingTimer = setTimeout(() => {
      trailingTimer = undefined;
      if (trailingArgs !== undefined) {
        invoke(trailingArgs);
        trailingArgs = undefined;
      }
    }, Math.max(0, waitMs - elapsed));
  };
}

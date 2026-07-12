import { throttle } from '@/utils/data/throttle';

describe('throttle', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('runs immediately and then invokes the latest queued call', () => {
    const callback = jest.fn();
    const throttled = throttle(callback, 100);

    throttled('first');
    throttled('second');
    throttled('latest');

    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenLastCalledWith('first');

    jest.advanceTimersByTime(100);

    expect(callback).toHaveBeenCalledTimes(2);
    expect(callback).toHaveBeenLastCalledWith('latest');
  });
});

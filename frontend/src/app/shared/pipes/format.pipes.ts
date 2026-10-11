import { Pipe, PipeTransform } from '@angular/core';
import {
  DateInput,
  Numeric,
  formatCop,
  formatDate,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
  formatTime,
  formatTimeAgo,
} from '../../core/format';

/** {{ 1234.5 | esNumber:1 }} -> 1.234,5 ; {{ x | esNumber:0:2 }} -> up to 2 decimals */
@Pipe({ name: 'esNumber' })
export class EsNumberPipe implements PipeTransform {
  transform(value: Numeric, minDecimals = 0, maxDecimals = minDecimals): string {
    return formatNumber(value, minDecimals, maxDecimals);
  }
}

/** {{ 27783 | cop }} -> $27.783 */
@Pipe({ name: 'cop' })
export class CopPipe implements PipeTransform {
  transform(value: Numeric): string {
    return formatCop(value);
  }
}

/** {{ 73 | esPercent }} -> 73 % ; {{ 0.731 | esPercent:1:true }} -> 73,1 % */
@Pipe({ name: 'esPercent' })
export class EsPercentPipe implements PipeTransform {
  transform(value: Numeric, decimals = 0, isRatio = false): string {
    return formatPercent(value, decimals, isRatio);
  }
}

/** {{ iso | esDate }} -> 06/10/2026 */
@Pipe({ name: 'esDate' })
export class EsDatePipe implements PipeTransform {
  transform(value: DateInput): string {
    return formatDate(value);
  }
}

/** {{ iso | esTime }} -> 11:14 p. m. */
@Pipe({ name: 'esTime' })
export class EsTimePipe implements PipeTransform {
  transform(value: DateInput): string {
    return formatTime(value);
  }
}

/** {{ iso | esDateTime }} -> 06/10/2026, 11:14 p. m. */
@Pipe({ name: 'esDateTime' })
export class EsDateTimePipe implements PipeTransform {
  transform(value: DateInput): string {
    return formatDateTime(value);
  }
}

/** {{ 185 | duration }} -> 03:05 (seconds in) */
@Pipe({ name: 'duration' })
export class DurationPipe implements PipeTransform {
  transform(seconds: Numeric): string {
    return formatDuration(seconds);
  }
}

/**
 * {{ iso | timeAgo }} -> hace 3 min. The pipe is pure: pass a ticking signal as argument
 * ({{ iso | timeAgo: clock.now() }}) when the text must refresh on its own.
 */
@Pipe({ name: 'timeAgo' })
export class TimeAgoPipe implements PipeTransform {
  transform(value: DateInput, now?: DateInput): string {
    return formatTimeAgo(value, now ?? new Date());
  }
}

/** Import this array in a component to get every es-CO pipe at once. */
export const FORMAT_PIPES = [
  EsNumberPipe,
  CopPipe,
  EsPercentPipe,
  EsDatePipe,
  EsTimePipe,
  EsDateTimePipe,
  DurationPipe,
  TimeAgoPipe,
] as const;

import { PriorityChip, StatusChip, TrafficLightBadge } from './ui/badges';
import { Button } from './ui/button';
import { Card } from './ui/card';
import { EmptyState, Skeleton } from './ui/feedback';
import { Icon } from './ui/icon';
import { Modal } from './ui/modal';
import { PhoneFrame } from './ui/phone-frame';
import { SectionHeader } from './ui/section-header';
import { DataTable } from './ui/table';
import {
  CopPipe,
  DurationPipe,
  EsDatePipe,
  EsDateTimePipe,
  EsNumberPipe,
  EsPercentPipe,
  EsTimePipe,
  TimeAgoPipe,
} from './pipes/format.pipes';

export * from './ui/badges';
export * from './ui/button';
export * from './ui/card';
export * from './ui/feedback';
export * from './ui/icon';
export * from './ui/modal';
export * from './ui/phone-frame';
export * from './ui/section-header';
export * from './ui/table';
export * from './ui/toast-host';
export * from './pipes/format.pipes';

/**
 * Everything a feature usually needs. In a component: `imports: [SHARED]`.
 * (ToastHost is not here: it is mounted once in the shell.)
 */
export const SHARED = [
  Icon,
  TrafficLightBadge,
  StatusChip,
  PriorityChip,
  Card,
  SectionHeader,
  DataTable,
  Button,
  Modal,
  EmptyState,
  Skeleton,
  PhoneFrame,
  EsNumberPipe,
  CopPipe,
  EsPercentPipe,
  EsDatePipe,
  EsTimePipe,
  EsDateTimePipe,
  DurationPipe,
  TimeAgoPipe,
] as const;

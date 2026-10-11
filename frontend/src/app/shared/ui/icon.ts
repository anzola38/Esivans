import { Component, computed, input } from '@angular/core';

/** Generic line icons drawn for this prototype (no third-party or brand artwork). */
const ICONS = {
  phone: ['M8 2.5h8a2 2 0 0 1 2 2v15a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-15a2 2 0 0 1 2-2z', 'M10.5 18.5h3'],
  chat: ['M4 5h16a1 1 0 0 1 1 1v9.5a1 1 0 0 1-1 1h-8l-4.5 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z', 'M7.5 9.5h9', 'M7.5 12.5h6'],
  console: ['M3.5 4.5h17a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-17a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z', 'M8.5 20.5h7', 'M12 16.5v4', 'M6.5 8.5h4', 'M6.5 12h7', 'M15 8.5l1.5 1.5 2.5-3'],
  bell: ['M6 16.5V11a6 6 0 0 1 12 0v5.500l1.500 2h-15z', 'M10 21h4'],
  chart: ['M4 4v16h16', 'M8 16v-4', 'M12 16V8', 'M16 16v-6'],
  refresh: ['M20 11a8 8 0 0 0-14.5-4.200L4 8.500', 'M4 4v4.500h4.500', 'M4 13a8 8 0 0 0 14.500 4.200L20 15.500', 'M20 20v-4.500h-4.500'],
  check: ['M5 12.5l4.5 4.5L19 7.5'],
  'check-circle': ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M8 12.300l2.700 2.700L16 9.500'],
  close: ['M6 6l12 12', 'M18 6L6 18'],
  alert: ['M12 4l9 15.500H3z', 'M12 10v4.500', 'M12 17v.400'],
  info: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 11v5.500', 'M12 7.500v.400'],
  clock: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7.500V12l3 2'],
  fuel: ['M12 3.500c3.500 4.300 5.500 7.200 5.500 10a5.500 5.500 0 0 1-11 0c0-2.800 2-5.700 5.500-10z'],
  gauge: ['M4 17a8 8 0 1 1 16 0', 'M12 17l4-5.500', 'M3 17h18'],
  camera: ['M4 8h3l1.500-2.500h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z', 'M12 10a3.500 3.500 0 1 0 0 7a3.500 3.500 0 0 0 0-7z'],
  send: ['M4 12l16-7.500-5.500 16-3-6.500z', 'M11.500 14L20 4.500'],
  clip: ['M19 11.500l-7.500 7.500a4.200 4.200 0 0 1-6-6l8-8a2.800 2.800 0 0 1 4 4l-8 8a1.400 1.400 0 0 1-2-2l7-7'],
  'chevron-right': ['M9 6l6 6-6 6'],
  'chevron-down': ['M6 9l6 6 6-6'],
  'arrow-left': ['M19 12H5', 'M11 6l-6 6 6 6'],
  'arrow-right': ['M5 12h14', 'M13 6l6 6-6 6'],
  inbox: ['M3.500 13.500l3-8h11l3 8v5a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1z', 'M3.500 13.500h5l1 2.500h5l1-2.500h5'],
  truck: ['M2.500 6.500h11v10h-11z', 'M13.500 10h4.500l3.500 3.500v3h-8z', 'M7 16.500a2 2 0 1 0 0 4a2 2 0 0 0 0-4z', 'M17 16.500a2 2 0 1 0 0 4a2 2 0 0 0 0-4z'],
  user: ['M12 4a4 4 0 1 0 0 8a4 4 0 0 0 0-8z', 'M4.500 20.500a7.500 7.500 0 0 1 15 0'],
  search: ['M11 4a7 7 0 1 0 0 14a7 7 0 0 0 0-14z', 'M16.500 16.500L21 21'],
  book: ['M5 4h13a1 1 0 0 1 1 1v15H6.500A1.500 1.500 0 0 1 5 18.500z', 'M5 18.500A1.500 1.500 0 0 1 6.500 17H19', 'M9 8h6', 'M9 11.500h4'],
  sliders: ['M4 7h10', 'M18 7h2', 'M4 17h4', 'M12 17h8', 'M16 5v4', 'M10 15v4'],
  shield: ['M12 3l8 3v6c0 4.500-3.200 8-8 9.500C7.200 20 4 16.500 4 12V6z', 'M9 12l2.200 2.200L15.200 10'],
  spark: ['M11 3l1.900 5.600L18.500 10.500l-5.600 1.900L11 18l-1.900-5.600L3.500 10.500l5.600-1.900z', 'M18.500 15.500v5', 'M16 18h5'],
  file: ['M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z', 'M14 3v5h5'],
  upload: ['M12 16V5', 'M7.500 9.500L12 5l4.500 4.500', 'M5 19h14'],
  plus: ['M12 5v14', 'M5 12h14'],
  edit: ['M4 20l1-4.500L16.500 4l3.500 3.500L8.500 19z', 'M14 6.500l3.500 3.500'],
  lock: ['M6 11h12v9H6z', 'M8.500 11V8a3.500 3.500 0 0 1 7 0v3'],
  eye: ['M2.500 12c2.500-4.500 5.700-6.500 9.500-6.500s7 2 9.500 6.500c-2.500 4.500-5.700 6.500-9.500 6.500S5 16.500 2.500 12z', 'M12 9.500a2.500 2.500 0 1 0 0 5a2.500 2.500 0 0 0 0-5z'],
  filter: ['M4 5h16l-6 7.500V19l-4-2v-4.500z'],
  scale: ['M12 4v16', 'M7 20h10', 'M5 7h14', 'M5 7l-2.500 6a2.700 2.700 0 0 0 5 0z', 'M19 7l-2.500 6a2.700 2.700 0 0 0 5 0z'],
  target: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7.500a4.500 4.500 0 1 0 0 9a4.500 4.500 0 0 0 0-9z', 'M12 11.600v.800'],
} as const;

export type IconName = keyof typeof ICONS;

export const ICON_NAMES = Object.keys(ICONS) as IconName[];

@Component({
  selector: 'app-icon',
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="size()"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      [attr.stroke-width]="strokeWidth()"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      @for (d of paths(); track $index) {
        <path [attr.d]="d" />
      }
    </svg>
  `,
})
export class Icon {
  readonly name = input.required<IconName>();
  /** Pixels. */
  readonly size = input(20);
  readonly strokeWidth = input(1.8);

  protected readonly paths = computed<readonly string[]>(() => ICONS[this.name()] ?? []);
}

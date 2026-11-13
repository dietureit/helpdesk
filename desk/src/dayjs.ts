import d from "dayjs";
import localizedFormat from "dayjs/plugin/localizedFormat";
import relativeTime from "dayjs/plugin/relativeTime";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { useAuthStore } from "./stores/auth";

const authStore = useAuthStore();
declare module "dayjs" {
  interface Dayjs {
    /** Example: `Aug 15, 2:29 AM` */
    short(): string;
    /** Example: `Tuesday, August 15, 2023 2:29 AM` */
    long(): string;
  }
}

d.extend(localizedFormat);
d.extend(relativeTime);
d.extend(function (_, cls) {
  cls.prototype.short = function () {
    return this.format("MMM D, h:mm A");
  };
  cls.prototype.long = function () {
    return this.format("LLLL");
  };
});
d.extend(utc);
d.extend(timezone);
d.tz.setDefault(authStore.timezone);

// Stored datetimes are naive system-timezone values. Parse them there, then
// shift to the logged-in user's timezone for display.
export function inSystemTz(value?: string) {
  if (!value) return d(value);
  const systemTz = authStore.systemTimezone;
  return systemTz ? d.tz(value, systemTz) : d(value);
}

export function formatInUserTz(value: string, format: string) {
  const parsed = inSystemTz(value);
  const userTz = authStore.timezone;
  return userTz ? parsed.tz(userTz).format(format) : parsed.format(format);
}

export const dayjs = d;

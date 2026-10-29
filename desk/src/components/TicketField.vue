<template>
  <div class="flex flex-col gap-1 px-5 py-2 first:pt-3">
    <label class="form-control-label text-xs text-gray-600">
      {{ field.label }}
      <span v-if="field.required" class="text-red-500">*</span>
    </label>

    <!-- Attach / Attach Image -->
    <div v-if="isAttach" class="flex flex-col gap-2 w-full">
      <div
        v-if="attachUrl"
        class="flex items-center gap-2 rounded-md border border-gray-200 bg-white px-2 py-1.5"
      >
        <img
          v-if="isImageAttach"
          :src="attachUrl"
          :alt="attachLabel"
          class="h-10 w-10 shrink-0 rounded object-cover border border-gray-100"
        />
        <a
          :href="attachUrl"
          target="_blank"
          class="flex-1 min-w-0 text-sm text-blue-600 hover:underline truncate"
        >
          {{ attachLabel }}
        </a>
      </div>
      <div class="flex items-center gap-1">
        <FileUploader
          v-if="!field.readonly && !field.disabled"
          :file-types="field.fieldtype === 'Attach Image' ? 'image/*' : undefined"
          :upload-args="{ folder: 'Home/Helpdesk', private: true }"
          @success="onAttachSuccess"
        >
          <template #default="{ openFileSelector, uploading }">
            <Button
              :loading="uploading"
              theme="gray"
              variant="outline"
              @click="openFileSelector()"
            >
              <template #prefix>
                <LucidePaperclip class="size-4" />
              </template>
              {{ attachUrl ? __("Replace") : __("Upload") }}
            </Button>
          </template>
        </FileUploader>
        <Button
          v-if="attachUrl && !field.readonly && !field.disabled"
          theme="gray"
          variant="ghost"
          @click="emitUpdate(field.fieldname, '')"
        >
          {{ __("Clear") }}
        </Button>
      </div>
    </div>

    <component
      v-else
      :is="component"
      :key="field.fieldname"
      :readonly="field.readonly"
      :disabled="field.disabled"
      class="form-control form-control-core w-full"
      :placeholder="field.placeholder || `Enter ${field.label}`"
      :model-value="transValue"
      autocomplete="off"
      v-on="
        [...textFields, ...numberFields].includes(field.fieldtype)
          ? {
              blur: (event) => {
                emitUpdate(field.fieldname, event.target.value);
              },
            }
          : {
              'update:model-value': (event) => {
                emitUpdate(
                  field.fieldname,
                  event?.value || event?.target?.value || event
                );
              },
            }
      "
    />
  </div>
</template>

<script setup lang="ts">
import { Autocomplete, Link } from "@/components";
import { APIOptions, Field, FieldValue } from "@/types";
import { parseApiOptions } from "@/utils";
import { __ } from "@/translation";
import {
  Button,
  createResource,
  DatePicker,
  DateTimePicker,
  dayjs,
  FileUploader,
  FormControl,
} from "frappe-ui";
import { computed, h } from "vue";
import LucidePaperclip from "~icons/lucide/paperclip";

interface P {
  field: Field;
  value: FieldValue;
}

interface R {
  fieldname: Field["fieldname"];
  value: FieldValue;
}

interface E {
  (event: "change", value: R);
}

const props = defineProps<P>();
const emit = defineEmits<E>();

const apiOptions = createResource({
  url: props.field.url_method,
  auto: !!props.field.url_method,
  transform: (data: APIOptions) => {
    return parseApiOptions(data);
  },
});

const textFields = ["Long Text", "Small Text", "Text", "Text Editor", "Data"];
const numberFields = ["Int", "Float", "Currency", "Percent"];
const longTextFields = new Set(["Long Text", "Text Editor", "Text", "Small Text"]);

const isAttach = computed(
  () =>
    props.field.fieldtype === "Attach" || props.field.fieldtype === "Attach Image"
);

const isImageAttach = computed(() => {
  if (props.field.fieldtype === "Attach Image") return true;
  const url = attachUrl.value.toLowerCase();
  return /\.(png|jpe?g|gif|webp|bmp|svg)(\?|$)/i.test(url);
});

const attachUrl = computed(() => {
  const v = props.value;
  return typeof v === "string" && v ? v : "";
});

const attachLabel = computed(() => {
  const url = attachUrl.value;
  if (!url) return "";
  try {
    return decodeURIComponent(url.split("/").pop() || url);
  } catch {
    return url;
  }
});

function onAttachSuccess(file: { file_url?: string }) {
  if (file?.file_url) emitUpdate(props.field.fieldname, file.file_url);
}

const component = computed(() => {
  if (props.field.url_method) {
    return h(Autocomplete, {
      options: apiOptions.data,
    });
  } else if (props.field.fieldtype === "Link" && props.field.options) {
    return h(Link, {
      doctype: props.field.options,
      hideMe: true,
    });
  } else if (props.field.fieldtype === "Select") {
    return h(Autocomplete, {
      options: props.field.options
        .split("\n")
        .map((o) => ({ label: o, value: o })),
    });
  } else if (props.field.fieldtype === "Check") {
    return h(Autocomplete, {
      options: [
        {
          label: "Yes",
          value: 1,
        },
        {
          label: "No",
          value: 0,
        },
      ],
    });
  } else if (textFields.includes(props.field.fieldtype)) {
    const isLong = longTextFields.has(props.field.fieldtype);
    return h(FormControl, {
      type: "textarea",
      rows: isLong ? 4 : 1,
    });
  } else if (props.field.fieldtype === "Datetime") {
    return h(DateTimePicker, {
      formatter: (datetime: string) => {
        if (!datetime) return datetime;
        return dayjs(datetime).format(
          `${window.date_format.toUpperCase()} ${window.time_format}`
        );
      },
    });
  } else if (props.field.fieldtype === "Date") {
    return h(DatePicker, {
      id: props.field.fieldname,
      // transValue hands over the site-formatted date; without the format the picker can't parse it and shows blank
      format: window.date_format?.toUpperCase(),
    });
  } else {
    return h(FormControl);
  }
});

const transValue = computed(() => {
  const fieldtype = props.field.fieldtype;
  if (fieldtype === "Check") {
    return props.value ? "Yes" : "No";
  } else if (fieldtype === "Date") {
    if (!props.value) return props.value;
    return dayjs(props.value).format(window.date_format.toUpperCase());
  }
  return props.value;
});

function emitUpdate(fieldname: Field["fieldname"], value: FieldValue) {
  emit("change", { fieldname, value });
}
</script>
<style scoped>
:deep(.form-control input:not([type="checkbox"])),
:deep(.form-control select),
:deep(.form-control textarea),
:deep(.form-control button) {
  border-color: #e5e7eb;
  background: white;
}

:deep(.form-control textarea) {
  min-height: 2.5rem;
}

:deep(.form-control button) {
  gap: 0;
}
:deep(.form-control [type="checkbox"]) {
  margin-left: 9px;
  cursor: pointer;
}

:deep(.form-control button > div) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

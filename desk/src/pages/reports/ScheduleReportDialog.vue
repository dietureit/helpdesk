<template>
  <Dialog v-model="show" :options="{ size: 'xl' }">
    <template #body-title>
      <h3 class="text-2xl font-semibold leading-6 text-gray-900">
        Scheduled Report Emails
      </h3>
    </template>
    <template #body-content>
      <div class="flex flex-col gap-4">
        <!-- Existing schedules -->
        <div v-if="schedules.data?.length" class="flex flex-col gap-2">
          <div
            v-for="s in schedules.data"
            :key="s.name"
            class="flex items-center justify-between gap-2 rounded border border-gray-200 px-3 py-2"
          >
            <div class="text-sm text-gray-700 min-w-0">
              <div class="font-medium truncate">{{ s.recipients }}</div>
              <div class="text-gray-500">
                {{ s.frequency }} at {{ s.send_time.slice(0, 5) }} ·
                {{ s.attach_format }}
                <span v-if="!s.enabled" class="text-orange-500">· Paused</span>
              </div>
            </div>
            <div class="flex shrink-0 gap-2">
              <Button :label="s.enabled ? 'Pause' : 'Resume'" @click="togglePause(s)" />
              <Button label="Edit" @click="edit(s)" />
              <Button label="Delete" theme="red" @click="remove(s)" />
            </div>
          </div>
        </div>
        <div v-else class="text-sm text-gray-500">No schedules yet.</div>

        <!-- Add / edit form -->
        <div class="flex flex-col gap-3 rounded border border-gray-200 p-3">
          <div class="text-sm font-medium text-gray-900">
            {{ form.name ? "Edit schedule" : "New schedule" }}
          </div>
          <div>
            <div class="mb-1.5 text-sm text-gray-600">Recipients (To)</div>
            <TextInput
              v-model="form.recipients"
              variant="outline"
              placeholder="a@example.com, b@example.com"
            />
          </div>
          <div>
            <div class="mb-1.5 text-sm text-gray-600">CC</div>
            <TextInput
              v-model="form.cc"
              variant="outline"
              placeholder="c@example.com"
            />
          </div>
          <div class="grid grid-cols-3 gap-3">
            <div>
              <div class="mb-1.5 text-sm text-gray-600">Frequency</div>
              <select v-model="form.frequency" class="w-full text-sm rounded border-gray-300">
                <option>Daily</option>
                <option>Weekly</option>
                <option>Monthly</option>
              </select>
            </div>
            <div>
              <div class="mb-1.5 text-sm text-gray-600">Send time</div>
              <input
                v-model="form.send_time"
                type="time"
                class="w-full text-sm rounded border-gray-300"
              />
            </div>
            <div>
              <div class="mb-1.5 text-sm text-gray-600">Attachment</div>
              <select v-model="form.attach_format" class="w-full text-sm rounded border-gray-300">
                <option>PDF</option>
                <option>Excel</option>
                <option>Both</option>
              </select>
            </div>
          </div>
          <div v-if="error" class="text-sm text-red-500">{{ error }}</div>
          <div class="flex gap-2">
            <Button
              :label="form.name ? 'Update' : 'Create'"
              variant="solid"
              @click="save"
            />
            <Button v-if="form.name" label="Cancel" @click="resetForm" />
          </div>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { Button, TextInput, call, createListResource } from "frappe-ui";
import { reactive, ref } from "vue";

const show = defineModel<boolean>();
const error = ref("");

const DOCTYPE = "HD Report Schedule";

const schedules = createListResource({
  doctype: DOCTYPE,
  fields: ["name", "enabled", "recipients", "cc", "frequency", "send_time", "attach_format"],
  orderBy: "creation desc",
  pageLength: 50,
  auto: true,
});

const emptyForm = {
  name: "",
  recipients: "",
  cc: "",
  frequency: "Monthly",
  send_time: "09:00",
  attach_format: "PDF",
};
const form = reactive({ ...emptyForm });

function resetForm() {
  Object.assign(form, emptyForm);
  error.value = "";
}

function edit(s) {
  Object.assign(form, {
    name: s.name,
    recipients: s.recipients,
    cc: s.cc || "",
    frequency: s.frequency,
    send_time: s.send_time.slice(0, 5),
    attach_format: s.attach_format,
  });
}

async function save() {
  error.value = "";
  try {
    const fields = {
      recipients: form.recipients,
      cc: form.cc,
      frequency: form.frequency,
      send_time: form.send_time + ":00",
      attach_format: form.attach_format,
    };
    if (form.name) {
      await call("frappe.client.set_value", {
        doctype: DOCTYPE,
        name: form.name,
        fieldname: fields,
      });
    } else {
      await call("frappe.client.insert", {
        doc: { doctype: DOCTYPE, enabled: 1, ...fields },
      });
    }
    resetForm();
    schedules.reload();
  } catch (e) {
    error.value = e.messages?.join(", ") || e.message || "Failed to save";
  }
}

async function togglePause(s) {
  await call("frappe.client.set_value", {
    doctype: DOCTYPE,
    name: s.name,
    fieldname: { enabled: s.enabled ? 0 : 1 },
  });
  schedules.reload();
}

async function remove(s) {
  await call("frappe.client.delete", { doctype: DOCTYPE, name: s.name });
  schedules.reload();
}
</script>

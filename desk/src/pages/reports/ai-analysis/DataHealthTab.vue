<template>
  <div class="space-y-6">
    <div
      v-if="error"
      class="flex flex-wrap items-center gap-2 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50"
    >
      <span class="flex-1 min-w-0">{{ error }}</span>
      <Button size="sm" :label="__('Retry')" @click="load" />
    </div>

    <div v-if="!health && loading" class="space-y-4 animate-pulse">
      <div v-for="i in 4" :key="i" class="h-40 bg-gray-100 rounded-lg" />
    </div>

    <template v-if="health">
      <p v-if="loading" class="text-xs text-gray-400">{{ __("Refreshing…") }}</p>

      <!-- Sources & coverage -->
      <section class="space-y-2">
        <h2 class="text-base font-semibold text-gray-900">{{ __("Sources & coverage") }}</h2>
        <div class="overflow-x-auto bg-white border border-gray-200 rounded-lg">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-left text-gray-500 border-b border-gray-200">
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Source") }}</th>
                <th class="px-3 py-2 font-medium text-right whitespace-nowrap">{{ __("Records") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("First") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Last") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Covered until") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Feed") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="s in health.sources || []"
                :key="s.key"
                class="border-b border-gray-100 last:border-b-0"
              >
                <td class="px-3 py-2 text-gray-900 whitespace-nowrap">{{ __(s.label) }}</td>
                <td class="px-3 py-2 text-right text-gray-700">{{ num(s.rows) }}</td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ fmtDate(s.first) }}</td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ fmtDate(s.last) }}</td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ fmtDate(s.until) }}</td>
                <td class="px-3 py-2 whitespace-nowrap">
                  <Tooltip v-if="s.stopped" :text="__('No covered week in more than 2 weeks')">
                    <Badge theme="orange" :label="__('Stopped')" />
                  </Tooltip>
                  <Badge v-else-if="s.until" theme="green" :label="__('Covered')" />
                  <span v-else class="text-gray-400">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <ul v-if="health.capture_notices?.length" class="space-y-1 text-sm text-amber-800">
          <li v-for="n in health.capture_notices" :key="n.key" class="flex items-start gap-2">
            <LucideTriangleAlert class="mt-0.5 size-4 shrink-0" />
            <span>{{ n.text }}</span>
          </li>
        </ul>
      </section>

      <!-- Exclusions -->
      <section class="space-y-2">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-base font-semibold text-gray-900">{{ __("Exclusions") }}</h2>
          <Button v-if="canDecide" :label="__('Add exclusion')" @click="openDialog('add')">
            <template #prefix><LucidePlus class="size-4" /></template>
          </Button>
        </div>
        <ul class="text-sm text-gray-700 list-disc list-inside">
          <li>
            {{
              rules.start_date
                ? __("Contacts before {0} are left out.", fmtDate(rules.start_date))
                : __("No start date is set.")
            }}
          </li>
          <li>
            {{
              rules.exclude_staff_phones
                ? __("Staff phones are left out.")
                : __("Staff phones are counted.")
            }}
          </li>
          <li>{{ __("Exclusions from the list below.") }}</li>
        </ul>
        <div v-if="byReason.length" class="flex flex-wrap gap-1">
          <!-- not a Badge: Badge never wraps, and a long reason must not widen the page on a phone -->
          <span
            v-for="[reason, n] in byReason"
            :key="reason"
            class="px-2 py-0.5 text-xs text-gray-600 bg-gray-100 rounded"
          >
            {{ __("{0}: {1} contacts", reason, num(n)) }}
          </span>
        </div>
        <p v-if="flash.section === 'exclusions'" class="text-sm" :class="toneClass">{{ flash.text }}</p>
        <p
          v-if="!exclusionRows.length"
          class="p-4 text-sm text-gray-500 bg-white border border-gray-200 rounded-lg"
        >
          {{ __("No exclusions.") }}
        </p>
        <div v-else class="overflow-x-auto bg-white border border-gray-200 rounded-lg">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-left text-gray-500 border-b border-gray-200">
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Type") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Value") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Reason") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Added by") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("When") }}</th>
                <th v-if="canDecide" class="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in visibleExclusions"
                :key="row.name"
                class="border-b border-gray-100 last:border-b-0 align-top"
              >
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ __(row.type) }}</td>
                <td class="px-3 py-2 font-mono text-xs text-gray-700 whitespace-nowrap">
                  {{ row.value === "hidden" ? __("hidden") : row.value }}
                </td>
                <td class="px-3 py-2 text-gray-700">
                  <span
                    class="block max-w-xs whitespace-pre-line"
                    dir="auto"
                    :class="getFontFamily(row.reason || '')"
                  >
                    {{ row.reason }}
                  </span>
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ row.owner || "—" }}</td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ fmtDateTime(row.creation) }}</td>
                <td v-if="canDecide" class="px-3 py-1 text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    :label="__('Remove')"
                    @click="openDialog('remove', { target: row })"
                  />
                </td>
              </tr>
            </tbody>
          </table>
          <div
            v-if="exclusionRows.length > PAGE"
            class="flex flex-wrap items-center gap-2 px-3 py-2 text-xs text-gray-500 border-t border-gray-200"
          >
            <span v-if="!showAllExclusions">
              {{ __("Showing the first {0} of {1}.", String(PAGE), num(exclusionRows.length)) }}
            </span>
            <Button
              size="sm"
              variant="ghost"
              :label="showAllExclusions ? __('Show fewer') : __('Show all')"
              @click="showAllExclusions = !showAllExclusions"
            />
          </div>
        </div>

        <div v-if="canDecide && suggested.length" class="pt-2 space-y-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3 class="text-sm font-medium text-gray-900">{{ __("Suggested exclusions") }}</h3>
            <Button
              :label="__('Exclude selected ({0})', String(selectedItems.length))"
              :disabled="!selectedItems.length"
              @click="openBulk"
            />
          </div>
          <div class="overflow-x-auto bg-white border border-gray-200 rounded-lg">
            <table class="min-w-full text-sm">
              <thead>
                <tr class="text-left text-gray-500 border-b border-gray-200">
                  <th class="w-8 px-3 py-2">
                    <input
                      type="checkbox"
                      class="rounded border-gray-300"
                      :checked="allPicked"
                      :aria-label="__('Select all')"
                      @change="pickAll"
                    />
                  </th>
                  <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Suggestion") }}</th>
                  <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Type") }}</th>
                  <th class="px-3 py-2 font-medium text-right whitespace-nowrap">{{ __("Contacts") }}</th>
                  <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Why") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="s in suggested"
                  :key="keyOf(s)"
                  class="border-b border-gray-100 last:border-b-0"
                >
                  <td class="px-3 py-2">
                    <input
                      v-model="picked"
                      type="checkbox"
                      class="rounded border-gray-300"
                      :value="keyOf(s)"
                      :disabled="!s.value"
                      :aria-label="s.label"
                    />
                  </td>
                  <td class="px-3 py-2 text-gray-700">{{ s.label }}</td>
                  <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ __(s.type) }}</td>
                  <td class="px-3 py-2 text-right text-gray-700">{{ num(s.contacts) }}</td>
                  <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ s.reason_hint || "—" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- NEW queue -->
      <section class="space-y-2">
        <h2 class="text-base font-semibold text-gray-900">
          {{ __("NEW queue") }}
          <span class="text-sm font-normal text-gray-500">({{ num(newQueue.length) }})</span>
        </h2>
        <p class="text-sm text-gray-500">
          {{ __("Labels the AI could not fit to a code, grouped by similar wording.") }}
        </p>
        <p v-if="flash.section === 'new'" class="text-sm" :class="toneClass">{{ flash.text }}</p>
        <p
          v-if="!newQueue.length"
          class="p-4 text-sm text-gray-500 bg-white border border-gray-200 rounded-lg"
        >
          {{ __("Nothing is waiting for a code.") }}
        </p>
        <div
          v-for="g in newQueue"
          :key="g.key"
          class="p-4 space-y-2 bg-white border border-gray-200 rounded-lg"
        >
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <span
              class="font-medium text-gray-900 whitespace-pre-line"
              dir="auto"
              :class="getFontFamily(g.label || '')"
            >
              {{ g.label }}
            </span>
            <span class="text-sm text-gray-500">{{ __("{0} contacts", num(g.n)) }}</span>
          </div>
          <ul class="space-y-1">
            <li
              v-for="(example, i) in g.examples || []"
              :key="i"
              class="p-2 text-sm text-gray-700 rounded bg-gray-50 whitespace-pre-line"
              dir="auto"
              :class="getFontFamily(example || '')"
            >
              {{ example }}
            </li>
          </ul>
          <div class="flex flex-wrap items-center text-xs gap-x-3 gap-y-1">
            <button
              v-for="(ref, i) in (g.refs || []).slice(0, 5)"
              :key="ref"
              type="button"
              class="text-gray-600 hover:underline"
              @click="openCase(ref)"
            >
              {{ __("Case {0} ↗", String(i + 1)) }}
            </button>
            <span v-if="(g.refs || []).length > 5" class="text-gray-400">
              {{ __("and {0} more", num(g.refs.length - 5)) }}
            </span>
          </div>
          <div v-if="canDecide" class="flex flex-wrap items-center gap-2 pt-1">
            <select
              v-model="mapTo[g.key]"
              :class="selectClass"
              class="max-w-full"
              :aria-label="__('Map to code')"
            >
              <option :value="undefined">{{ __("Map to code…") }}</option>
              <option v-for="c in mappableCodes" :key="c.code" :value="c.code">
                {{ c.code }} — {{ c.label }}
              </option>
            </select>
            <Button
              :label="__('Map')"
              :disabled="!mapTo[g.key] || !!busyGroup"
              :loading="busyGroup === g.key + ':map'"
              @click="newAction(g, 'map_new')"
            />
            <Button :label="__('Create code ↗')" @click="createCode(g)" />
            <Button
              :label="__('Dismiss')"
              :disabled="!!busyGroup"
              :loading="busyGroup === g.key + ':dismiss'"
              @click="newAction(g, 'dismiss_new')"
            />
          </div>
        </div>
      </section>

      <!-- Registry -->
      <section class="space-y-2">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-base font-semibold text-gray-900">
            {{ __("Issue codes") }}
            <span class="text-sm font-normal text-gray-500">({{ num(registry.length) }})</span>
          </h2>
          <Button
            v-if="canDecide"
            :label="__('Edit in Desk ↗')"
            @click="openDesk('/app/hd-ai-issue-code')"
          />
        </div>
        <div class="overflow-auto bg-white border border-gray-200 rounded-lg max-h-96">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-left text-gray-500 border-b border-gray-200">
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Code") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Label") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Kind") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Owner") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Floor") }}</th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Status") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in registry"
                :key="r.code"
                class="border-b border-gray-100 last:border-b-0"
                :title="r.definition || ''"
              >
                <td class="px-3 py-2 font-mono text-xs text-gray-900 whitespace-nowrap">{{ r.code }}</td>
                <td class="px-3 py-2 text-gray-700">
                  {{ r.label }}
                  <Badge v-if="r.is_food_safety" theme="red" :label="__('Food safety')" class="ml-1" />
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ __(r.kind || "—") }}</td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ r.owner_department || "—" }}</td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ r.severity_floor || "—" }}</td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ __(r.status || "—") }}
                  <span v-if="r.merged_into" class="text-gray-500">→ {{ r.merged_into }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Publish label version -->
      <section class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
        <h2 class="text-base font-semibold text-gray-900">{{ __("Label version") }}</h2>
        <dl class="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <div class="min-w-0">
            <dt class="text-xs text-gray-500">{{ __("Current version") }}</dt>
            <dd class="font-mono text-xs text-gray-900 break-all">{{ version.current || "—" }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500">{{ __("Contacts to re-label") }}</dt>
            <dd class="text-gray-900">{{ num(version.stale) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500">{{ __("Estimate") }}</dt>
            <dd class="text-gray-900">
              {{
                version.stale
                  ? __("≈ {0} · {1}", usd(version.estimate_usd), hoursText(version.estimate_hours))
                  : "—"
              }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500">{{ __("AI budget left this month") }}</dt>
            <dd class="text-gray-900">{{ usd(version.budget_left) }}</dd>
          </div>
        </dl>
        <div v-if="canDecide" class="flex flex-wrap items-center gap-2">
          <Button
            variant="solid"
            :label="__('Publish')"
            :disabled="!!publishBlocked"
            @click="openDialog('publish')"
          />
          <span v-if="publishBlocked" class="text-xs text-gray-500">{{ publishBlocked }}</span>
        </div>
        <p v-if="flash.section === 'publish'" class="text-sm" :class="toneClass">{{ flash.text }}</p>
      </section>

      <!-- Quality -->
      <section class="p-4 space-y-4 bg-white border border-gray-200 rounded-lg">
        <h2 class="text-base font-semibold text-gray-900">{{ __("Quality") }}</h2>
        <dl class="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <div class="col-span-2 md:col-span-1">
            <dt class="text-xs text-gray-500">{{ __("Quotes") }}</dt>
            <dd class="text-gray-900">{{ quoteMix }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500">{{ __("Wrong-label rate") }}</dt>
            <dd class="text-gray-900">{{ pct(quality.wrong_label_rate) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500">{{ __("NEW share") }}</dt>
            <dd class="text-gray-900">{{ pct(quality.new_share) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500">{{ __("Failed contacts") }}</dt>
            <dd class="text-gray-900">{{ num(quality.failed) }}</dd>
          </div>
        </dl>

        <div class="space-y-1">
          <h3 class="text-sm font-medium text-gray-900">{{ __("Food-safety rule precision") }}</h3>
          <p v-if="!quality.safety_rules?.length" class="text-sm text-gray-500">
            {{ __("No rule hits yet.") }}
          </p>
          <div v-else class="overflow-x-auto border border-gray-200 rounded-lg">
            <table class="min-w-full text-sm">
              <thead>
                <tr class="text-left text-gray-500 border-b border-gray-200">
                  <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Rule") }}</th>
                  <th class="px-3 py-2 font-medium text-right whitespace-nowrap">{{ __("Hits") }}</th>
                  <th class="px-3 py-2 font-medium text-right whitespace-nowrap">
                    {{ __("Confirmed by a food-safety label") }}
                  </th>
                  <th class="px-3 py-2 font-medium text-right whitespace-nowrap">{{ __("Precision") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="r in quality.safety_rules"
                  :key="r.rule"
                  class="border-b border-gray-100 last:border-b-0"
                >
                  <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ ruleLabel(r.rule) }}</td>
                  <td class="px-3 py-2 text-right text-gray-700">{{ num(r.hits) }}</td>
                  <td class="px-3 py-2 text-right text-gray-700">{{ num(r.confirmed) }}</td>
                  <td class="px-3 py-2 text-right text-gray-700">
                    {{ r.hits ? pct(r.confirmed / r.hits) : "—" }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="space-y-1">
          <h3 class="text-sm font-medium text-gray-900">{{ __("Gold-set score") }}</h3>
          <p v-if="!score" class="text-sm text-gray-600">
            {{ __("Not yet validated — treat trends as directional.") }}
          </p>
          <div v-else class="space-y-1 text-sm text-gray-700">
            <div class="flex flex-wrap items-center gap-2">
              <Badge
                :theme="score.ok ? 'green' : 'orange'"
                :label="score.ok ? __('Validated') : __('Not validated')"
              />
              <span class="text-xs text-gray-500">{{ __("Scored {0}", fmtDateTime(score.scored_on)) }}</span>
            </div>
            <p>
              {{
                __(
                  "Safety recall {0} · quote validity {1} · macro-F1 {2} · agreement κ {3} · {4} contacts",
                  pct(score.safety_recall),
                  pct(score.quote_validity),
                  dec(score.macro_f1),
                  dec(gold.kappa ?? score.kappa),
                  num(score.n)
                )
              }}
            </p>
          </div>
        </div>

        <dl class="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          <div>
            <dt class="text-xs text-gray-500">{{ __("AI spend this month") }}</dt>
            <dd class="text-gray-900">
              {{ __("{0} of {1}", usd(health.spend?.month_usd), usd(health.spend?.budget_usd)) }}
            </dd>
          </div>
          <div class="min-w-0">
            <dt class="text-xs text-gray-500">{{ __("Models and prompt version") }}</dt>
            <dd class="text-gray-900 break-words">
              <div>{{ __("Labelling: {0}", models.tagging || "—") }}</div>
              <div>{{ __("Council: {0}", (models.council || []).join(", ") || "—") }}</div>
              <div>{{ __("Chairman: {0}", models.chairman || "—") }}</div>
              <div>{{ __("Research: {0}", models.research || "—") }}</div>
              <div class="font-mono text-xs break-all">
                {{ __("Prompt version: {0}", models.prompt_version || "—") }}
              </div>
            </dd>
          </div>
        </dl>
      </section>

      <!-- Gold set (deciders) -->
      <section v-if="canDecide" class="p-4 space-y-2 bg-white border border-gray-200 rounded-lg">
        <h2 class="text-base font-semibold text-gray-900">{{ __("Gold set") }}</h2>
        <p class="text-sm text-gray-700">
          {{ __("{0} gold-label rows, {1} marked final.", num(gold.sampled), num(gold.labelled)) }}
          {{ __("Two people label the same contacts blind; the score checks the AI against them.") }}
        </p>
        <div class="flex flex-wrap gap-2">
          <Button :label="__('Create gold sample')" @click="openDialog('gold')" />
          <Button :label="__('Open gold labels in Desk ↗')" @click="openDesk('/app/hd-ai-gold-label')" />
        </div>
        <p v-if="flash.section === 'gold'" class="text-sm" :class="toneClass">{{ flash.text }}</p>
      </section>

      <!-- Capture hygiene -->
      <section class="p-4 space-y-2 bg-white border border-gray-200 rounded-lg">
        <h2 class="text-base font-semibold text-gray-900">{{ __("Capture hygiene") }}</h2>
        <p class="text-sm text-gray-700">
          {{
            __(
              "{0} of {1} tickets ({2}) have the type Unspecified.",
              num(hygiene.unspecified),
              num(hygiene.tickets),
              pct(hygiene.unspecified_share)
            )
          }}
        </p>
        <p class="text-sm text-gray-500">
          {{ __("Ignored: these ticket fields default to a real-looking value, so they are never read.") }}
        </p>
        <div class="flex flex-wrap gap-1">
          <Badge v-for="f in hygiene.ignored_fields || []" :key="f" :label="f" />
        </div>
      </section>
    </template>

    <Dialog v-model="dlg.open" :options="{ title: dialogTitle, size: 'md' }">
      <template #body-content>
        <div class="space-y-3">
          <template v-if="dlg.kind === 'add'">
            <label class="block space-y-1.5">
              <span class="text-xs text-gray-600">{{ __("Type") }}</span>
              <select v-model="dlg.type" class="w-full text-sm border-gray-300 rounded">
                <option v-for="t in EXCLUSION_TYPES" :key="t" :value="t">{{ __(t) }}</option>
              </select>
            </label>
            <label class="block space-y-1.5">
              <span class="text-xs text-gray-600">{{ __("Value") }}</span>
              <input
                v-model="dlg.value"
                type="text"
                class="w-full text-sm border-gray-300 rounded"
                :placeholder="valueHint(dlg.type)"
              />
            </label>
          </template>
          <p v-else-if="dlg.kind === 'remove'" class="text-sm text-gray-700">
            {{
              __(
                "Stop excluding {0} {1}. The row stays in the history with your reason.",
                __(dlg.target?.type || ""),
                dlg.target?.value || ""
              )
            }}
          </p>
          <p v-else-if="dlg.kind === 'bulk'" class="text-sm text-gray-700">
            {{ __("Exclude {0} selected suggestions; one reason covers them all.", String(selectedItems.length)) }}
          </p>
          <p v-else-if="dlg.kind === 'publish'" class="text-sm text-gray-700">
            {{
              __(
                "Re-label {0} contacts that carry an older label version, for about {1} ({2}). Numbers settle as they are re-labelled; confirmed and rejected reviews carry over.",
                num(version.stale),
                usd(version.estimate_usd),
                hoursText(version.estimate_hours)
              )
            }}
          </p>
          <template v-else-if="dlg.kind === 'gold'">
            <p class="text-sm text-gray-700">
              {{ __("About 80 contacts are sampled. Both people label the first 20, so their agreement can be measured; neither sees the AI labels.") }}
            </p>
            <Link
              v-model="dlg.users[0]"
              doctype="User"
              :filters="{ enabled: 1, user_type: 'System User' }"
              :hide-me="true"
              :label="__('First labeller')"
              :placeholder="__('Pick a person')"
            />
            <Link
              v-model="dlg.users[1]"
              doctype="User"
              :filters="{ enabled: 1, user_type: 'System User' }"
              :hide-me="true"
              :label="__('Second labeller')"
              :placeholder="__('Pick a person')"
            />
          </template>
          <label v-if="needsReason" class="block space-y-1.5">
            <span class="text-xs text-gray-600">{{ __("Reason (required)") }}</span>
            <textarea
              v-model="dlg.reason"
              rows="3"
              dir="auto"
              maxlength="500"
              class="w-full text-sm border-gray-300 rounded"
            />
          </label>
          <p v-if="dlg.error" class="text-sm text-red-600">{{ dlg.error }}</p>
        </div>
      </template>
      <template #actions>
        <div class="flex justify-end gap-2">
          <Button :label="__('Cancel')" @click="dlg.open = false" />
          <Button
            variant="solid"
            :theme="dlg.kind === 'remove' ? 'red' : 'gray'"
            :label="submitLabel"
            :loading="dlg.busy"
            @click="submitDialog"
          />
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import Link from "@/components/frappe-ui/Link.vue";
import { dayjs } from "@/dayjs";
import { __ } from "@/translation";
import { getFontFamily } from "@/utils";
import { Badge, Button, Dialog, Tooltip, call } from "frappe-ui";
import { computed, reactive, ref, watch } from "vue";
import LucidePlus from "~icons/lucide/plus";
import LucideTriangleAlert from "~icons/lucide/triangle-alert";

const props = defineProps<{
  filters?: Record<string, any>;
  status?: Record<string, any> | null;
  canDecide?: boolean;
}>();
const emit = defineEmits<{
  (e: "open-issue", code: string): void;
  (e: "jump", window: { from_date: string; to_date: string }): void;
  (e: "refresh-status"): void;
}>();

const API = "helpdesk.api.ai_analysis.";
const EXCLUSION_TYPES = ["Ticket", "Conversation", "Phone", "Contact"];
const PAGE = 20;
const selectClass = "text-sm rounded-lg border-gray-200 py-1.5";

const health = ref<Record<string, any> | null>(null);
const loading = ref(false);
const error = ref("");
let loadSeq = 0;

async function load() {
  const seq = ++loadSeq;
  loading.value = true;
  error.value = "";
  try {
    const data = await call(API + "get_data_health");
    if (seq === loadSeq) health.value = data;
  } catch (e) {
    if (seq === loadSeq) error.value = errText(e);
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

const rules = computed(() => health.value?.exclusions?.rules || {});
const byReason = computed(() => Object.entries(health.value?.exclusions?.by_reason || {}));
const exclusionRows = computed<Record<string, any>[]>(() => health.value?.exclusions?.rows || []);
const showAllExclusions = ref(false);
const visibleExclusions = computed(() =>
  showAllExclusions.value ? exclusionRows.value : exclusionRows.value.slice(0, PAGE)
);
const suggested = computed<Record<string, any>[]>(() => health.value?.suggested || []);
const newQueue = computed<Record<string, any>[]>(() => health.value?.new_queue || []);
const registry = computed<Record<string, any>[]>(() => health.value?.registry || []);
const mappableCodes = computed(() => registry.value.filter((r) => r.status === "Active" && r.code !== "NEW"));
const version = computed(() => health.value?.version || {});
const quality = computed(() => health.value?.quality || {});
const gold = computed(() => health.value?.gold || {});
const score = computed(() => gold.value.score || null);
const models = computed(() => health.value?.models || {});
const hygiene = computed(() => health.value?.hygiene || {});

const quoteMix = computed(() => {
  const mix: Record<string, number> = quality.value.quote_status || {};
  const total = Object.values(mix).reduce((a, b) => a + (Number(b) || 0), 0);
  return (
    Object.entries(mix)
      .map(([status, n]) => `${__(status)} ${num(n)} (${pct(total ? n / total : null)})`)
      .join(" · ") || "—"
  );
});

const publishBlocked = computed(() => {
  const s = props.status;
  if (!s) return __("Checking whether AI is available…");
  if (!s.ai_ready) return s.ai_reason || __("AI is off.");
  if (!s.worker_running) return __("Background worker not running.");
  if (!version.value.stale) return __("Every labelled contact already has the current label version.");
  return "";
});

// --- results of actions, shown in the section that ran them -------------------------------------
const flash = reactive({ section: "", tone: "ok", text: "" });
const toneClass = computed(
  () => ({ ok: "text-green-700", info: "text-gray-700", error: "text-red-600" })[flash.tone]
);
function say(section: string, tone: string, text: string) {
  Object.assign(flash, { section, tone, text });
}

// every action: POST, then refresh the status strip and this tab
async function run(method: string, args: Record<string, any>) {
  const res = await call(API + method, args);
  emit("refresh-status");
  load();
  return res;
}

// --- suggested exclusions ----------------------------------------------------------------------
const picked = ref<string[]>([]);
const keyOf = (s: Record<string, any>) => `${s.type}:${s.value}`;
const selectedItems = computed(() => suggested.value.filter((s) => s.value && picked.value.includes(keyOf(s))));
const allPicked = computed(
  () => suggested.value.some((s) => s.value) && suggested.value.every((s) => !s.value || picked.value.includes(keyOf(s)))
);
function pickAll(e: Event) {
  picked.value = (e.target as HTMLInputElement).checked
    ? suggested.value.filter((s) => s.value).map(keyOf)
    : [];
}
function openBulk() {
  const hints = [...new Set(selectedItems.value.map((s) => s.reason_hint).filter(Boolean))];
  openDialog("bulk", { reason: hints.join("; ") });
}

// --- NEW queue ---------------------------------------------------------------------------------
const mapTo = reactive<Record<string, string | undefined>>({});
const busyGroup = ref("");

async function newAction(g: Record<string, any>, method: "map_new" | "dismiss_new") {
  const code = mapTo[g.key];
  // ponytail: one call carries at most 500 refs (the endpoint's cap); a bigger group needs a second click
  const args: Record<string, any> = { refs: JSON.stringify((g.refs || []).slice(0, 500)) };
  if (method === "map_new") args.code = code;
  busyGroup.value = `${g.key}:${method === "map_new" ? "map" : "dismiss"}`;
  try {
    const res = await run(method, args);
    say(
      "new",
      "ok",
      method === "map_new"
        ? __("{0} labels mapped to {1}.", num(res?.mapped), code || "")
        : __("{0} labels dismissed.", num(res?.dismissed))
    );
  } catch (e) {
    say("new", "error", errText(e));
  } finally {
    busyGroup.value = "";
  }
}

function createCode(g: Record<string, any>) {
  const label = g.label || "";
  const code = label.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  const query = new URLSearchParams({ label });
  if (code) query.set("code", code);
  openDesk(`/app/hd-ai-issue-code/new?${query}`);
  window.addEventListener("focus", load, { once: true }); // back from Desk: pick up the new code
}

// --- the one dialog: add / remove / bulk exclude / publish / gold sample ------------------------
const dlg = reactive({
  open: false,
  kind: "",
  type: "Ticket",
  value: "",
  reason: "",
  users: ["", ""],
  target: null as Record<string, any> | null,
  error: "",
  busy: false,
});
const needsReason = computed(() => ["add", "remove", "bulk"].includes(dlg.kind));
const dialogTitle = computed(
  () =>
    ({
      add: __("Add exclusion"),
      remove: __("Remove exclusion"),
      bulk: __("Exclude selected"),
      publish: __("Publish label version"),
      gold: __("Create gold sample"),
    })[dlg.kind] || ""
);
const submitLabel = computed(
  () =>
    ({
      add: __("Exclude"),
      remove: __("Remove"),
      bulk: __("Exclude"),
      publish: __("Publish"),
      gold: __("Create"),
    })[dlg.kind] || __("Save")
);

function openDialog(kind: string, init: Record<string, any> = {}) {
  Object.assign(
    dlg,
    { kind, type: "Ticket", value: "", reason: "", users: ["", ""], target: null, error: "", busy: false },
    init,
    { open: true }
  );
}

function valueHint(type: string) {
  return (
    {
      Ticket: __("Ticket number, e.g. 164"),
      Conversation: __("Conversation name, or a case ref"),
      Phone: __("Phone number (the last 8 digits are kept)"),
      Contact: __("Case ref (one chat session or ticket)"),
    }[type] || ""
  );
}

function request(): [string, string, Record<string, any>, (res: any) => string] {
  const reason = dlg.reason.trim();
  switch (dlg.kind) {
    case "add":
      return [
        "exclusions",
        "add_exclusion",
        { exclusion_type: dlg.type, value: dlg.value.trim(), reason },
        (res) =>
          res?.name ? __("Excluded; {0} contacts changed.", num(res.changed)) : res?.message || __("Already excluded."),
      ];
    case "remove":
      return [
        "exclusions",
        "remove_exclusion",
        { name: dlg.target?.name, reason },
        (res) => __("Exclusion removed; {0} contacts changed.", num(res?.changed)),
      ];
    case "bulk":
      return [
        "exclusions",
        "exclude_suggested",
        { items: JSON.stringify(selectedItems.value.map((s) => ({ type: s.type, value: s.value }))), reason },
        (res) =>
          __(
            "{0} excluded, {1} already excluded; {2} contacts changed.",
            num(res?.added),
            num(res?.skipped),
            num(res?.changed)
          ),
      ];
    case "publish":
      return ["publish", "publish_version", {}, (res) => res?.message || ""];
    default:
      return [
        "gold",
        "gold_sample",
        { labellers: JSON.stringify(dlg.users) },
        (res) => __("{0} gold-label rows created.", num(res?.created)),
      ];
  }
}

async function submitDialog() {
  if (needsReason.value && !dlg.reason.trim()) return void (dlg.error = __("A reason is required."));
  if (dlg.kind === "add" && !dlg.value.trim()) return void (dlg.error = __("Enter what to exclude."));
  if (dlg.kind === "gold" && (!dlg.users[0] || !dlg.users[1] || dlg.users[0] === dlg.users[1]))
    return void (dlg.error = __("Pick two different people."));
  const [section, method, args, message] = request();
  dlg.busy = true;
  dlg.error = "";
  try {
    const res = await run(method, args);
    // add_exclusion answers {name: null, message} and publish_version {started: false, message} when nothing ran
    say(section, res?.name === null || res?.started === false ? "info" : "ok", message(res));
    if (dlg.kind === "bulk") picked.value = [];
    dlg.open = false;
  } catch (e) {
    dlg.error = errText(e);
  } finally {
    dlg.busy = false;
  }
}

// --- small helpers ------------------------------------------------------------------------------
function openCase(ref: string) {
  window.open(
    "/api/method/helpdesk.api.ai_analysis.open_case?ref=" + encodeURIComponent(ref),
    "_blank",
    "noopener"
  );
}
function openDesk(path: string) {
  window.open(path, "_blank", "noopener");
}
function errText(e: any): string {
  return (e?.messages?.length ? e.messages.join(" ") : e?.message) || __("Something went wrong.");
}
function ruleLabel(rule: string) {
  const text = String(rule || "").replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
function fmtDate(d?: string | null) {
  return d ? dayjs(d).format("D MMM YYYY") : "—";
}
function fmtDateTime(d?: string | null) {
  return d ? dayjs(d).format("D MMM YYYY, h:mm A") : "—";
}
function num(n?: number | null) {
  return n == null ? "—" : Number(n).toLocaleString("en");
}
function pct(x?: number | null) {
  if (x == null) return "—";
  const p = x * 100;
  return `${p < 10 ? Math.round(p * 10) / 10 : Math.round(p)}%`; // small rates keep one decimal: 0.7%
}
function dec(x?: number | null) {
  return x == null ? "—" : Number(x).toFixed(2);
}
function usd(x?: number | null) {
  return x == null ? "—" : `$${Number(x).toFixed(2)}`;
}
function hoursText(h?: number | null) {
  if (h == null) return "—";
  return h < 0.1 ? __("under 6 minutes") : __("{0} h", Number(h).toFixed(1));
}

// a finished analysis run changes the numbers
watch(
  () => props.status?.running,
  (now, was) => {
    if (was && !now) load();
  }
);
load();
</script>

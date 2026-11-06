<template>
  <div class="space-y-4 break-words">
    <!-- Council: several models propose options, a chairman rates them and writes one plan -->
    <section class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div class="min-w-0">
          <h3 class="text-sm font-medium text-gray-900">{{ __("Suggestions") }}</h3>
          <p class="text-xs text-gray-500">
            {{ __("Several AI models propose options from the verified quotes, an independent model rates them and writes one plan, and code checks every reference. A manager decides.") }}
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <select
            v-if="versions.length > 1"
            :value="sug.s.name"
            :class="selectClass"
            class="max-w-full"
            :aria-label="__('Plan version')"
            @change="onVersion"
          >
            <option v-for="v in versions" :key="v.name" :value="v.name">{{ v.label }}</option>
          </select>
          <template v-if="!isRunning(sd)">
            <Button
              :variant="sd ? 'subtle' : 'solid'"
              :label="__('Get suggestions')"
              :disabled="!!aiBlock || sugReq.loading"
              :loading="sugReq.loading && !sugReq.regenerate"
              @click="requestSuggestions(0)"
            >
              <template #prefix><LucideSparkles class="w-4 h-4" /></template>
            </Button>
            <Button
              v-if="sd"
              variant="subtle"
              :label="__('Regenerate')"
              :disabled="!!aiBlock || sugReq.loading"
              :loading="sugReq.loading && !!sugReq.regenerate"
              @click="requestSuggestions(1)"
            >
              <template #prefix><LucideRefreshCw class="w-4 h-4" /></template>
            </Button>
          </template>
        </div>
      </div>
      <p v-if="aiBlock" class="text-xs text-gray-500">{{ aiBlock }}</p>
      <div v-if="sugReq.error" :class="noticeClass">{{ sugReq.error }}</div>
      <p v-if="sugReq.reused" class="text-xs text-gray-500">
        {{ __("The evidence hasn't changed since the last run, so it is shown again. Use Regenerate for a fresh one.") }}
      </p>

      <div v-if="sug.s.error" :class="errorClass">
        <span class="flex-1 min-w-0">{{ sug.s.error }}</span>
        <Button :label="__('Retry')" :loading="sug.s.loading" @click="sug.load()" />
      </div>

      <div v-if="sug.s.loading && !sd" class="space-y-2 animate-pulse">
        <div class="w-2/3 h-4 bg-gray-200 rounded"></div>
        <div class="h-24 bg-gray-100 rounded"></div>
      </div>
      <p v-else-if="!sd && !sug.s.error" class="text-sm text-gray-500">
        {{ __("No suggestions yet for this issue.") }}
      </p>

      <div v-else-if="isRunning(sd)" class="flex items-center gap-2 p-3 text-sm text-gray-700 border border-gray-200 rounded-lg">
        <LoadingIndicator class="w-4 h-4 shrink-0" />
        <span>{{ progressText(sd) }}</span>
      </div>

      <div v-else-if="sd?.status === 'Failed'" :class="errorClass">
        <span class="flex-1 min-w-0">{{ sd.error || __("The run failed.") }}</span>
        <Button
          :label="__('Retry')"
          :disabled="!!aiBlock"
          :loading="sugReq.loading"
          @click="requestSuggestions(1)"
        />
      </div>

      <template v-else-if="finished">
        <div v-if="sd.stale" :class="noticeClass" class="flex flex-wrap items-center gap-3">
          <span class="flex-1 min-w-0">{{ __("Evidence changed since this run — Regenerate for a fresh plan") }}</span>
          <Button
            :label="__('Regenerate')"
            :disabled="!!aiBlock || sugReq.loading"
            :loading="sugReq.loading"
            @click="requestSuggestions(1)"
          />
        </div>

        <div
          v-if="decided"
          class="p-3 space-y-1 text-sm border rounded-lg"
          :class="sd.decision === 'Adopted' ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-800'"
        >
          <div class="font-medium">{{ decisionText }}</div>
          <p
            v-if="sd.decision_note"
            class="whitespace-pre-line"
            dir="auto"
            :class="font(sd.decision_note)"
          >{{ sd.decision_note }}</p>
        </div>
        <div v-else-if="canAct" class="flex flex-wrap items-center gap-2">
          <span class="flex-1 min-w-0 text-xs text-gray-500">
            {{ __("Adopt a card, tick options or steps to combine them into a new version, or reject the plan with a reason.") }}
          </span>
          <Button theme="red" variant="subtle" :label="__('Reject plan')" @click="openReject" />
        </div>
        <div
          v-if="adopted"
          class="flex flex-wrap items-center gap-2 p-3 text-sm text-green-800 border border-green-200 rounded-lg bg-green-50"
        >
          <span class="flex-1 min-w-0">
            {{ __("Adopted as action {0}. The assignee gets a ToDo.", adopted) }}
          </span>
          <Button variant="subtle" :label="__('Open the Actions tab')" @click="goActions" />
        </div>

        <p
          v-if="sd.status === 'No synthesis'"
          class="p-3 text-sm text-gray-700 border border-gray-200 rounded-lg bg-gray-50"
        >
          {{ __("No synthesis: the chairman model could not write a valid plan, so there are no cards. The options below are ranked by score.") }}
        </p>

        <!-- The 3 cards: Quick win, Structural fix, Combined plan -->
        <div v-if="cards.length" class="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div
            v-for="card in cards"
            :key="card.type"
            class="flex flex-col gap-3 p-3 border border-gray-200 rounded-lg"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <Badge :label="lbl(card.type)" :theme="card.type === 'combined_plan' ? 'blue' : 'gray'" />
              <span v-if="card.success_metric" class="text-xs text-gray-500">
                {{ __("Measured as {0}", lbl(card.success_metric)) }}
              </span>
            </div>
            <p class="text-sm font-medium text-gray-900 whitespace-pre-line" dir="auto" :class="font(card.title)">{{ card.title }}</p>
            <p
              v-if="card.why"
              class="text-sm text-gray-700 whitespace-pre-line"
              dir="auto"
              :class="font(card.why)"
            >{{ card.why }}</p>
            <ol v-if="card.steps?.length" class="space-y-2">
              <li v-for="(step, i) in card.steps" :key="i" class="flex items-start gap-2">
                <input
                  v-if="canAct && step.from_options?.length"
                  type="checkbox"
                  class="mt-0.5 rounded-sm border-gray-300"
                  :checked="stepPicked(step)"
                  :aria-label="__('Use this step')"
                  @change="onStep(step, $event)"
                />
                <div class="flex-1 min-w-0 space-y-1">
                  <div class="text-xs text-gray-500">
                    {{ lbl(step.when) }} · {{ step.owner_department || "—" }}
                  </div>
                  <p class="text-sm text-gray-800 whitespace-pre-line" dir="auto" :class="font(step.action)">{{ step.action }}</p>
                  <div v-if="step.from_options?.length" class="flex flex-wrap gap-1">
                    <button
                      v-for="id in step.from_options"
                      :key="id"
                      type="button"
                      :class="chipClass"
                      @click="scrollToOption(id)"
                    >
                      {{ __("from {0}", id) }}
                    </button>
                  </div>
                </div>
              </li>
            </ol>
            <div v-for="f in textFields(card, CARD_FIELDS)" :key="f.key">
              <div class="text-xs font-medium text-gray-500">{{ f.label }}</div>
              <p class="text-sm text-gray-700 whitespace-pre-line" dir="auto" :class="font(f.text)">{{ f.text }}</p>
            </div>
            <div v-if="canAct" class="pt-1 mt-auto">
              <Button variant="solid" :label="__('Adopt')" @click="openAdopt(card)" />
            </div>
          </div>
        </div>

        <!-- Options O1..On -->
        <div v-if="options.length" class="space-y-2">
          <h4 class="text-sm font-medium text-gray-900">
            {{ __("Options ({0})", String(options.length)) }}
          </h4>
          <div
            v-for="o in options"
            :id="optDomId(o.id)"
            :key="o.id"
            class="p-3 border border-gray-200 rounded-lg"
            :class="{ 'ring-2 ring-gray-400': flash === o.id }"
          >
            <div class="flex items-start gap-2">
              <input
                v-if="canAct"
                v-model="picked"
                type="checkbox"
                :value="o.id"
                class="mt-1 rounded-sm border-gray-300"
                :aria-label="__('Select {0}', o.id)"
              />
              <div class="flex-1 min-w-0 space-y-2">
                <div class="flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
                  <span class="font-semibold text-gray-900">{{ o.id }}</span>
                  <span v-if="o.lens">{{ o.lens }}</span>
                  <Badge v-if="o.tier" size="sm" :label="lbl(o.tier)" />
                  <Badge v-if="o.external" size="sm" theme="orange" :label="__('External idea')" />
                  <span v-if="o.also_proposed_by?.length">{{ alsoText(o) }}</span>
                  <span v-if="o.score != null" class="ml-auto font-medium text-gray-900">
                    {{ __("Score {0}", String(o.score)) }}
                  </span>
                </div>
                <p class="text-sm font-medium text-gray-900 whitespace-pre-line" dir="auto" :class="font(o.title)">{{ o.title }}</p>
                <p
                  v-if="o.hypothesis"
                  class="text-sm text-gray-700 whitespace-pre-line"
                  dir="auto"
                  :class="font(o.hypothesis)"
                >{{ o.hypothesis }}</p>
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="[k, label] in RATINGS"
                    :key="k"
                    class="px-1.5 py-0.5 text-xs rounded"
                    :class="RATING_CLASS[o.ratings?.[k]] || 'bg-gray-100 text-gray-500'"
                  >
                    {{ label }}: {{ lbl(o.ratings?.[k]) }}
                  </span>
                </div>
                <div v-if="o.evidence_refs?.length" class="flex flex-wrap items-center gap-1">
                  <span class="text-xs text-gray-500">{{ __("Evidence") }}</span>
                  <button
                    v-for="r in o.evidence_refs"
                    :key="r"
                    type="button"
                    class="px-1.5 py-0.5 text-xs rounded"
                    :class="ev?.at === o.id && ev?.id === r ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'"
                    @click="toggleEv(o.id, r)"
                  >
                    {{ r }}
                  </button>
                </div>
                <div
                  v-if="ev?.at === o.id"
                  class="p-3 space-y-1 text-sm border border-gray-200 rounded-lg bg-gray-50"
                >
                  <template v-if="evItem">
                    <div class="flex flex-wrap items-center gap-x-2 text-xs text-gray-500">
                      <span class="font-medium text-gray-700">{{ evItem.id }}</span>
                      <span v-if="evItem.date">{{ fmtDate(evItem.date) }}</span>
                      <span v-if="evItem.channel">{{ evItem.channel }}</span>
                      <span v-if="evItem.severity">{{ evItem.severity }}</span>
                      <span v-if="evItem.role">{{ roleLabel(evItem.role) }}</span>
                      <Button
                        v-if="evItem.ref"
                        class="ml-auto"
                        size="sm"
                        variant="ghost"
                        :label="__('Open ↗')"
                        @click="openCase(evItem.ref)"
                      />
                    </div>
                    <p class="text-gray-900 whitespace-pre-line" dir="auto" :class="font(evItem.quote)">{{ evItem.quote }}</p>
                    <template v-if="evItem.quote_en && evItem.quote_en !== evItem.quote">
                      <div class="text-xs text-gray-500">{{ __("AI translation") }}</div>
                      <p class="text-gray-700 whitespace-pre-line" dir="auto" :class="font(evItem.quote_en)">{{ evItem.quote_en }}</p>
                    </template>
                  </template>
                  <template v-else-if="extItem">
                    <div class="text-xs text-gray-500">{{ extItem.id }} · {{ __("External source, not verified against Dieture data") }}</div>
                    <p class="text-gray-900 whitespace-pre-line" dir="auto" :class="font(extItem.title)">{{ extItem.title }}</p>
                    <a
                      v-if="safeUrl(extItem.url)"
                      :href="safeUrl(extItem.url) || undefined"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="inline-flex items-center gap-1 text-xs text-gray-600 underline hover:text-gray-900"
                    >
                      {{ extItem.domain || domainOf(extItem.url) || __("Source") }}
                      <LucideExternalLink class="w-3 h-3" />
                    </a>
                  </template>
                  <p v-else class="text-gray-500">{{ __("This reference is no longer available.") }}</p>
                </div>
                <details class="text-sm">
                  <summary class="text-xs text-gray-600 cursor-pointer select-none">{{ __("Details") }}</summary>
                  <div class="mt-2 space-y-2">
                    <div v-if="o.action_steps?.length">
                      <div class="text-xs font-medium text-gray-500">{{ __("Action steps") }}</div>
                      <ol class="pl-5 space-y-1 list-decimal">
                        <li
                          v-for="(s, i) in o.action_steps"
                          :key="i"
                          class="text-gray-800 whitespace-pre-line"
                          dir="auto"
                          :class="font(s)"
                        >{{ s }}</li>
                      </ol>
                    </div>
                    <div class="flex flex-wrap text-xs text-gray-600 gap-x-4 gap-y-1">
                      <span>{{ __("Owner: {0}", o.owner_department || "—") }}</span>
                      <span>{{ __("Effort: {0}", o.effort || "—") }}</span>
                      <span>{{ __("Cost: {0}", lbl(o.cost_band)) }}</span>
                      <span>{{ __("Time to effect: {0}", lbl(o.time_to_effect)) }}</span>
                      <span v-if="o.success_metric">{{ __("Success metric: {0}", lbl(o.success_metric)) }}</span>
                    </div>
                    <div v-for="f in textFields(o, OPTION_FIELDS)" :key="f.key">
                      <div class="text-xs font-medium text-gray-500">{{ f.label }}</div>
                      <p class="text-gray-700 whitespace-pre-line" dir="auto" :class="font(f.text)">{{ f.text }}</p>
                    </div>
                    <div v-for="f in textFields(o.rating_notes, RATINGS)" :key="'note-' + f.key">
                      <div class="text-xs font-medium text-gray-500">{{ __("Rating note: {0}", f.label) }}</div>
                      <p class="text-gray-700 whitespace-pre-line" dir="auto" :class="font(f.text)">{{ f.text }}</p>
                    </div>
                  </div>
                </details>
              </div>
            </div>
          </div>
        </div>

        <div v-if="canAct && options.length" class="p-3 space-y-2 border border-gray-200 rounded-lg bg-gray-50">
          <p class="text-xs text-gray-600">
            {{ __("Tick options, or steps on the cards, then combine them: the chairman rewrites the plan from only those options and saves it as a new version.") }}
          </p>
          <Textarea v-model="combineNote" :rows="2" :placeholder="__('Note for the chairman (optional)')" />
          <div class="flex flex-wrap items-center gap-2">
            <Button
              :label="__('Combine selected ({0})', String(picked.length))"
              :disabled="picked.length < 2 || !!aiBlock"
              :loading="combineReq.loading"
              @click="combine"
            />
            <span v-if="picked.length < 2" class="text-xs text-gray-500">{{ __("Select at least 2 options.") }}</span>
            <span v-else-if="aiBlock" class="text-xs text-gray-500">{{ aiBlock }}</span>
          </div>
          <p v-if="combineReq.error" class="text-sm text-red-700">{{ combineReq.error }}</p>
        </div>

        <details v-if="rejected.length" class="text-sm">
          <summary class="text-xs text-gray-600 cursor-pointer select-none">
            {{ __("Rejected options ({0})", String(rejected.length)) }}
          </summary>
          <ul class="mt-2 space-y-2">
            <li v-for="(r, i) in rejected" :key="i">
              <p class="text-gray-800 whitespace-pre-line" dir="auto" :class="font(r.title)">{{ r.title }}</p>
              <p class="text-xs text-gray-500 whitespace-pre-line" dir="auto" :class="font(r.reason)">{{ r.reason }}</p>
            </li>
          </ul>
        </details>

        <div v-if="out.disagreements?.length || out.what_would_change_my_mind" class="space-y-2">
          <h4 v-if="out.disagreements?.length" class="text-sm font-medium text-gray-900">
            {{ __("Where the options disagree") }}
          </h4>
          <ul v-if="out.disagreements?.length" class="space-y-2">
            <li v-for="(d, i) in out.disagreements" :key="i" class="space-y-1 text-sm">
              <p class="text-gray-800 whitespace-pre-line" dir="auto" :class="font(d.about)">{{ d.about }}</p>
              <div v-if="d.options?.length" class="flex flex-wrap gap-1">
                <button
                  v-for="id in d.options"
                  :key="id"
                  type="button"
                  :class="chipClass"
                  @click="scrollToOption(id)"
                >
                  {{ id }}
                </button>
              </div>
              <template v-if="d.check_first">
                <div class="text-xs font-medium text-gray-500">{{ __("Check first") }}</div>
                <p class="text-gray-700 whitespace-pre-line" dir="auto" :class="font(d.check_first)">{{ d.check_first }}</p>
              </template>
            </li>
          </ul>
          <div v-if="out.what_would_change_my_mind">
            <div class="text-xs font-medium text-gray-500">{{ __("What would change my mind") }}</div>
            <p
              class="text-sm text-gray-700 whitespace-pre-line"
              dir="auto"
              :class="font(out.what_would_change_my_mind)"
            >{{ out.what_would_change_my_mind }}</p>
          </div>
        </div>

        <p v-if="footnote" class="text-xs text-gray-400">{{ footnote }}</p>
      </template>
    </section>

    <!-- Research fixes: web search on a de-identified problem card -->
    <section class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div class="min-w-0">
          <h3 class="text-sm font-medium text-gray-900">{{ __("Research fixes") }}</h3>
          <p class="text-xs text-gray-500">
            {{ __("Searches the web for proven countermeasures. Only a de-identified problem card is sent, and you see it before anything leaves.") }}
          </p>
        </div>
        <Button
          v-if="!isRunning(rd)"
          :label="researchDone ? __('Refresh research') : __('Research fixes')"
          :disabled="!!researchBlock"
          @click="openPreview"
        >
          <template #prefix><LucideGlobe class="w-4 h-4" /></template>
        </Button>
      </div>
      <p v-if="researchBlock" class="text-xs text-gray-500">{{ researchBlock }}</p>
      <p v-if="researchReused" class="text-xs text-gray-500">
        {{ __("Recent results for this issue already exist, so they are shown again.") }}
      </p>

      <div v-if="research.s.error" :class="errorClass">
        <span class="flex-1 min-w-0">{{ research.s.error }}</span>
        <Button :label="__('Retry')" :loading="research.s.loading" @click="research.load()" />
      </div>

      <div v-if="research.s.loading && !rd" class="h-16 bg-gray-100 rounded animate-pulse"></div>
      <div v-else-if="isRunning(rd)" class="flex items-center gap-2 p-3 text-sm text-gray-700 border border-gray-200 rounded-lg">
        <LoadingIndicator class="w-4 h-4 shrink-0" />
        <span>{{ progressText(rd) }}</span>
      </div>
      <div v-else-if="rd?.status === 'Failed'" :class="errorClass">
        <span class="flex-1 min-w-0">{{ rd.error || __("The research failed.") }}</span>
        <Button :label="__('Retry')" :disabled="!!researchBlock" @click="openPreview" />
      </div>
      <div
        v-else-if="researchDone"
        class="p-4 space-y-3 border border-gray-200 rounded-lg bg-gray-50"
      >
        <div class="flex items-center gap-2">
          <LucideGlobe class="w-4 h-4 text-gray-600 shrink-0" />
          <h4 class="text-sm font-medium text-gray-900">
            {{ __("External — not verified against Dieture data") }}
          </h4>
        </div>
        <p class="text-xs text-gray-500">
          {{ __("Researched {0}", fromNow(rd.creation)) }}
          <template v-if="rd.stale"> · {{ __("these results are old; Refresh for new ones") }}</template>
        </p>
        <p v-if="rout.no_sources" class="text-sm text-gray-700">{{ __("No sources returned") }}</p>
        <ul v-if="rout.practices?.length" class="space-y-3">
          <li v-for="(p, i) in rout.practices" :key="i" class="space-y-1">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-medium text-gray-900 whitespace-pre-line" dir="auto" :class="font(p.title)">{{ p.title }}</span>
              <Badge v-if="p.effort" size="sm" :label="__('Effort {0}', p.effort)" />
            </div>
            <p
              v-if="p.what_to_do"
              class="text-sm text-gray-700 whitespace-pre-line"
              dir="auto"
              :class="font(p.what_to_do)"
            >{{ p.what_to_do }}</p>
            <template v-if="p.fit_for_dieture">
              <div class="text-xs font-medium text-gray-500">{{ __("Fit for Dieture") }}</div>
              <p class="text-sm text-gray-700 whitespace-pre-line" dir="auto" :class="font(p.fit_for_dieture)">{{ p.fit_for_dieture }}</p>
            </template>
            <a
              v-if="safeUrl(p.source_url)"
              :href="safeUrl(p.source_url) || undefined"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1 text-xs text-gray-600 underline hover:text-gray-900"
            >
              {{ domainOf(p.source_url) || p.domain || __("Source") }}
              <LucideExternalLink class="w-3 h-3" />
            </a>
          </li>
        </ul>
        <p v-else-if="!rout.no_sources" class="text-sm text-gray-500">{{ __("No practices returned.") }}</p>
        <div v-if="rout.caveats?.length">
          <div class="text-xs font-medium text-gray-500">{{ __("Caveats") }}</div>
          <ul class="pl-5 space-y-1 text-sm list-disc">
            <li
              v-for="(c, i) in rout.caveats"
              :key="i"
              class="text-gray-700 whitespace-pre-line"
              dir="auto"
              :class="font(c)"
            >{{ c }}</li>
          </ul>
        </div>
        <p v-if="rout.dropped > 0" class="text-xs text-gray-500">
          {{ __("{0} suggestions dropped (no valid source)", String(rout.dropped)) }}
        </p>
        <details v-if="rd.card || rout.card" class="text-sm">
          <summary class="text-xs text-gray-600 cursor-pointer select-none">{{ __("What was sent") }}</summary>
          <div
            class="p-3 mt-2 text-gray-700 whitespace-pre-line bg-white border border-gray-200 rounded"
            dir="auto"
            :class="font(rd.card || rout.card)"
          >{{ rd.card || rout.card }}</div>
        </details>
      </div>
    </section>

    <Dialog v-model="preview.open" :options="{ title: __('Research fixes on the web'), size: '2xl' }">
      <template #body-content>
        <div class="space-y-3">
          <div v-if="preview.loading && !preview.data" class="h-32 bg-gray-100 rounded animate-pulse"></div>
          <template v-else-if="preview.data">
            <p class="text-xs font-medium text-gray-500">{{ __("This text and nothing else is sent") }}</p>
            <div
              class="p-3 overflow-y-auto text-sm text-gray-800 whitespace-pre-line border border-gray-200 rounded max-h-72 bg-gray-50"
              dir="auto"
              :class="font(preview.data.card)"
            >{{ preview.data.card }}</div>
            <ul v-if="preview.data.checks?.length" class="space-y-1 text-sm">
              <li v-for="c in preview.data.checks" :key="c.name" class="flex items-center gap-2">
                <LucideCheck v-if="c.ok" class="w-4 h-4 text-green-600 shrink-0" />
                <LucideX v-else class="w-4 h-4 text-red-600 shrink-0" />
                <span :class="c.ok ? 'text-gray-700' : 'text-red-700'">{{ c.name }}</span>
              </li>
            </ul>
            <p v-if="!preview.data.ok" class="text-sm text-red-700">
              {{ __("A check failed, so nothing can be sent.") }}
            </p>
          </template>
          <div v-if="preview.error" :class="errorClass">
            <span class="flex-1 min-w-0">{{ preview.error }}</span>
            <Button v-if="!preview.data" :label="__('Retry')" :loading="preview.loading" @click="loadPreview" />
          </div>
        </div>
      </template>
      <template #actions>
        <div class="flex flex-wrap justify-end gap-2">
          <Button :label="__('Cancel')" @click="preview.open = false" />
          <Button
            variant="solid"
            :label="__('Send')"
            :disabled="!preview.data?.ok || !!researchBlock"
            :loading="preview.sending"
            @click="sendResearch"
          />
        </div>
      </template>
    </Dialog>

    <Dialog v-model="adoptDlg.open" :options="{ title: __('Adopt this plan'), size: 'lg' }">
      <template #body-content>
        <div class="space-y-3">
          <div>
            <div class="text-xs font-medium text-gray-500">{{ lbl(adoptDlg.card?.type) }}</div>
            <p
              class="text-sm text-gray-900 whitespace-pre-line"
              dir="auto"
              :class="font(adoptDlg.card?.title)"
            >{{ adoptDlg.card?.title }}</p>
          </div>
          <Link
            v-model="adoptDlg.assigned_to"
            class="form-control"
            doctype="HD Agent"
            :filters="{ is_active: 1 }"
            :hide-me="true"
            :label="__('Assign to')"
            :placeholder="__('Pick an agent')"
            required
          />
          <FormControl v-model="adoptDlg.due_date" type="date" :label="__('Due date')" />
          <FormControl
            v-model="adoptDlg.target"
            type="number"
            :label="adoptDlg.card?.success_metric ? __('Target, in {0} (optional)', lbl(adoptDlg.card.success_metric)) : __('Target (optional)')"
            :placeholder="__('Half the baseline')"
          />
          <p class="text-xs text-gray-500">
            {{ __("Code computes the baseline when you adopt. A blank target means half the baseline. The assignee gets a ToDo.") }}
          </p>
          <p v-if="adoptDlg.error" class="text-sm text-red-700">{{ adoptDlg.error }}</p>
        </div>
      </template>
      <template #actions>
        <div class="flex flex-wrap justify-end gap-2">
          <Button :label="__('Cancel')" @click="adoptDlg.open = false" />
          <Button
            variant="solid"
            :label="__('Adopt')"
            :disabled="!adoptDlg.assigned_to"
            :loading="adoptDlg.loading"
            @click="adopt"
          />
        </div>
      </template>
    </Dialog>

    <Dialog v-model="rejectDlg.open" :options="{ title: __('Reject this plan'), size: 'lg' }">
      <template #body-content>
        <div class="space-y-3">
          <FormControl
            v-model="rejectDlg.reason"
            type="select"
            :label="__('Reason')"
            :options="REASONS"
            :placeholder="__('Pick a reason')"
          />
          <FormControl
            v-model="rejectDlg.note"
            type="textarea"
            :label="rejectDlg.reason === 'Other' ? __('Note (required for Other)') : __('Note (optional)')"
          />
          <p v-if="rejectDlg.error" class="text-sm text-red-700">{{ rejectDlg.error }}</p>
        </div>
      </template>
      <template #actions>
        <div class="flex flex-wrap justify-end gap-2">
          <Button :label="__('Cancel')" @click="rejectDlg.open = false" />
          <Button
            theme="red"
            variant="solid"
            :label="__('Reject')"
            :disabled="!rejectDlg.reason || (rejectDlg.reason === 'Other' && !rejectDlg.note.trim())"
            :loading="rejectDlg.loading"
            @click="reject"
          />
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import Link from "@/components/frappe-ui/Link.vue";
import { dayjs } from "@/dayjs";
import { useUserStore } from "@/stores/user";
import { __ } from "@/translation";
import { getFontFamily } from "@/utils";
import { Badge, Button, call, Dialog, FormControl, LoadingIndicator, Textarea } from "frappe-ui";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import LucideCheck from "~icons/lucide/check";
import LucideExternalLink from "~icons/lucide/external-link";
import LucideGlobe from "~icons/lucide/globe";
import LucideRefreshCw from "~icons/lucide/refresh-cw";
import LucideSparkles from "~icons/lucide/sparkles";
import LucideX from "~icons/lucide/x";
import { domainOf, dueDateFor, roleLabel, safeUrl } from "./aiAnalysis";

type Row = Record<string, any>;

const props = defineProps<{
  code: string;
  kind?: string;
  filters?: Row;
  canDecide?: boolean;
  status?: Row | null;
  suggestions?: Row | null;
  research?: Row | null;
}>();
const emit = defineEmits<{ (e: "refresh-status"): void }>();

const API = "helpdesk.api.ai_analysis.";
const RUNNING = ["Queued", "Running"];
const WHEN = ["this_week", "this_month", "this_quarter"];
const selectClass = "text-sm rounded-lg border-gray-200 py-1.5";
const errorClass =
  "flex flex-wrap items-center gap-3 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50";
const noticeClass = "p-3 text-sm text-amber-800 border border-amber-200 rounded-lg bg-amber-50";
const chipClass = "px-1.5 py-0.5 text-xs text-gray-700 bg-gray-100 rounded hover:bg-gray-200";

const LABELS: Row = {
  quick_win: __("Quick win"),
  structural_fix: __("Structural fix"),
  combined_plan: __("Combined plan"),
  contain_now: __("Contain now"),
  process_fix: __("Process fix"),
  this_week: __("This week"),
  this_month: __("This month"),
  this_quarter: __("This quarter"),
  cases_per_week: __("cases per week"),
  customers_per_week: __("customers per week"),
  rate_per_1000_deliveries: __("cases per 1,000 deliveries"),
  strong: __("strong"),
  adequate: __("adequate"),
  weak: __("weak"),
  low: __("low"),
  medium: __("medium"),
  high: __("high"),
};
const RATINGS: [string, string][] = [
  ["grounded", __("Grounded")],
  ["specific", __("Specific")],
  ["feasible", __("Feasible")],
  ["measurable", __("Measurable")],
  ["risk", __("Risk")],
];
const RATING_CLASS: Row = {
  strong: "bg-green-50 text-green-700",
  adequate: "bg-gray-100 text-gray-700",
  weak: "bg-orange-50 text-orange-700",
};
const CARD_FIELDS: [string, string][] = [
  ["check_first", __("Check first")],
  ["risks", __("Risks")],
];
const OPTION_FIELDS: [string, string][] = [
  ["counter_evidence", __("Counter-evidence")],
  ["check_first", __("Check first")],
  ["expected_effect", __("Expected effect")],
  ["risks", __("Risks")],
];
const REASONS = ["Not feasible", "Already tried", "Wrong cause", "Too costly", "Other"].map((r) => ({
  label: __(r),
  value: r,
}));

const route = useRoute();
const router = useRouter();
const { getUser } = useUserStore();

const lbl = (k: unknown) => (typeof k === "string" && k ? LABELS[k] || k : "—");
// getFontFamily returns a Tailwind class (Arabic → system-ui), so it is bound as a class
const font = (t: unknown) => getFontFamily(typeof t === "string" ? t : "");
const errText = (e: any) =>
  (e?.messages?.length ? e.messages.join(" ") : "") || __("Something went wrong. Try again.");
const isRunning = (d: Row | null | undefined) => RUNNING.includes(d?.status);
const fmtDate = (d: unknown) => (d ? dayjs(d as string).format("D MMM YYYY") : "—");
const fmtDateTime = (d: unknown) => (d ? dayjs.tz(d as string).format("D MMM YYYY, h:mm A") : "—");
const fromNow = (d: unknown) => (d ? dayjs.tz(d as string).fromNow() : "—");
const textFields = (obj: Row | null | undefined, fields: [string, string][]) =>
  fields
    .filter(([k]) => typeof obj?.[k] === "string" && obj[k].trim())
    .map(([key, label]) => ({ key, label, text: obj![key] as string }));
const openCase = (ref: string) =>
  window.open(
    "/api/method/helpdesk.api.ai_analysis.open_case?ref=" + encodeURIComponent(ref),
    "_blank",
    "noopener"
  );

function progressText(d: Row | null | undefined) {
  if (d?.progress_label) return __(d.progress_label);
  if (d?.status === "Queued") return __("Queued, waiting for the background worker…");
  return d?.step ? __("Working… step {0}", String(d.step)) : __("Working…");
}

const aiBlock = computed(() => {
  const s = props.status;
  if (!s) return __("Checking whether AI is available…");
  if (!s.ai_ready) return s.ai_reason || __("AI is not available right now.");
  if (!s.worker_running) return __("Background worker not running");
  return "";
});
const researchBlock = computed(
  () => aiBlock.value || (props.status?.web_research ? "" : __("Web research is switched off in HD Settings."))
);

// One insight (Suggestions or Research): load by name, poll every 3 s while Queued/Running.
// `seq` drops stale replies (version switch, a newer reload, unmount).
function insightLoader() {
  const s = reactive({ name: "", data: null as Row | null, loading: false, error: "" });
  let seq = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  function reset() {
    seq++;
    clearTimeout(timer);
    Object.assign(s, { name: "", data: null, loading: false, error: "" });
  }
  async function load(name?: string) {
    clearTimeout(timer);
    if (name && name !== s.name) Object.assign(s, { name, data: null, error: "" });
    if (!s.name) return;
    const my = ++seq;
    s.loading = true;
    try {
      const data = await call(API + "get_insight", { name: s.name });
      if (my !== seq) return;
      const wasRunning = isRunning(s.data);
      s.data = data || null;
      s.error = "";
      if (isRunning(data)) timer = setTimeout(() => load(), 3000);
      else if (wasRunning) emit("refresh-status"); // a run finished: spend changed
    } catch (e) {
      if (my === seq) s.error = errText(e);
    } finally {
      if (my === seq) s.loading = false;
    }
  }
  return { s, load, reset };
}

const sug = insightLoader();
const research = insightLoader();
const sd = computed(() => sug.s.data);
const rd = computed(() => research.s.data);
const out = computed<Row>(() => sd.value?.output || {});
const rout = computed<Row>(() => rd.value?.output || {});
const finished = computed(() => ["Done", "No synthesis"].includes(sd.value?.status));
const researchDone = computed(() => rd.value?.status === "Done");
const cards = computed<Row[]>(() => (sd.value?.status === "Done" && out.value.cards) || []);
const options = computed<Row[]>(() => {
  const list: Row[] = [...(out.value.options || [])];
  if (sd.value?.status === "No synthesis") list.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  return list;
});
const rejected = computed<Row[]>(() => out.value.rejected || []);
const decided = computed(() => !!sd.value?.decision && sd.value.decision !== "Pending");
const canAct = computed(() => !!props.canDecide && finished.value && !decided.value);

const decisionText = computed(() => {
  const d = sd.value || {};
  const who = d.decided_by_name || (d.decided_by ? getUser(d.decided_by)?.full_name || d.decided_by : "—");
  const when = fmtDateTime(d.decided_on);
  if (d.decision === "Adopted") return __("Adopted by {0} on {1}", who, when);
  return __("Rejected by {0} on {1}: {2}", who, when, d.decision_reason ? __(d.decision_reason) : "—");
});

const versions = computed(() =>
  [...(sd.value?.history || [])]
    .sort((a: Row, b: Row) => String(a.creation).localeCompare(String(b.creation)))
    .map((v: Row, i: number) => ({
      name: v.name,
      label: [
        __("Version {0}", String(i + 1)),
        fmtDate(v.creation),
        v.parent_insight ? __("combined") : __("AI run"),
        v.note ? String(v.note).slice(0, 40) : "",
      ]
        .filter(Boolean)
        .join(" · "),
    }))
);

const footnote = computed(() => {
  const o = out.value;
  const state = (m: Row) => `${m.model} (${m.ok ? __("answered") : __("failed")})`;
  const parts: string[] = [];
  if (o.proposers?.length) parts.push(__("Proposers: {0}", o.proposers.map(state).join(", ")));
  if (o.chairman?.model) parts.push(__("Chairman: {0}", state(o.chairman)));
  if (!parts.length && sd.value?.models) parts.push(String(sd.value.models));
  if (sd.value?.creation) parts.push(__("Run on {0}", fmtDateTime(sd.value.creation)));
  return parts.join(" · ");
});

function alsoText(o: Row) {
  const n = o.also_proposed_by.length;
  return n === 1 ? __("Also proposed by 1 other model") : __("Also proposed by {0} other models", String(n));
}

// Evidence chip: one open at a time, shown inline under its option
const ev = ref<{ at: string; id: string } | null>(null);
const evItem = computed(() => (ev.value ? (out.value.evidence || []).find((e: Row) => e.id === ev.value!.id) : null));
const extItem = computed(() => (ev.value ? (out.value.external || []).find((x: Row) => x.id === ev.value!.id) : null));
function toggleEv(at: string, id: string) {
  ev.value = ev.value?.at === at && ev.value.id === id ? null : { at, id };
}

const flash = ref("");
const optDomId = (id: string) => `ai-opt-${sug.s.name}-${id}`;
function scrollToOption(id: string) {
  document.getElementById(optDomId(id))?.scrollIntoView({ behavior: "smooth", block: "center" });
  flash.value = id;
  setTimeout(() => flash.value === id && (flash.value = ""), 1500);
}

// --- Get suggestions / Regenerate ---
const sugReq = reactive({ loading: false, regenerate: 0, error: "", reused: false });
async function requestSuggestions(regenerate: 0 | 1) {
  Object.assign(sugReq, { loading: true, regenerate, error: "", reused: false });
  try {
    const r = await call(API + "request_suggestions", {
      code: props.code,
      from_date: props.filters?.from_date,
      to_date: props.filters?.to_date,
      regenerate,
    });
    sugReq.reused = !!r?.reused;
    resetPicks();
    adopted.value = "";
    if (r?.insight) await sug.load(r.insight);
  } catch (e) {
    sugReq.error = errText(e); // refusals (guard, worker, budget) are shown inline
    emit("refresh-status");
  } finally {
    sugReq.loading = false;
  }
}

// --- Combine selected (deciders): a ticked step stands for the options it came from ---
// ponytail: only option ids are sent, because the combine endpoint accepts option ids only. advisor.combine
// also takes step ids (cards[].steps[].id, "quick_win:1") and keeps those exact steps; once the endpoint
// accepts them, send the ticked steps' ids as well.
const picked = ref<string[]>([]);
const combineNote = ref("");
const combineReq = reactive({ loading: false, error: "" });
const stepPicked = (step: Row) => (step.from_options || []).every((id: string) => picked.value.includes(id));
function onStep(step: Row, e: Event) {
  const ids: string[] = step.from_options || [];
  picked.value = (e.target as HTMLInputElement).checked
    ? [...new Set([...picked.value, ...ids])]
    : picked.value.filter((id) => !ids.includes(id));
}
function resetPicks() {
  picked.value = [];
  combineNote.value = "";
  combineReq.error = "";
  ev.value = null;
}
async function combine() {
  combineReq.loading = true;
  combineReq.error = "";
  try {
    const r = await call(API + "combine", {
      insight: sug.s.name,
      selected: JSON.stringify(picked.value),
      note: combineNote.value.trim(),
    });
    resetPicks();
    if (r?.insight) await sug.load(r.insight);
  } catch (e) {
    combineReq.error = errText(e);
  } finally {
    combineReq.loading = false;
  }
}
function onVersion(e: Event) {
  resetPicks();
  sug.load((e.target as HTMLSelectElement).value);
}

// --- Adopt (per card) ---
const adopted = ref("");
const adoptDlg = reactive({
  open: false,
  card: null as Row | null,
  assigned_to: "",
  due_date: "",
  target: "",
  loading: false,
  error: "",
});
function openAdopt(card: Row) {
  // due date from the card's latest step: this_week +7, this_month +28, this_quarter +90 days
  const latest = Math.max(-1, ...(card.steps || []).map((s: Row) => WHEN.indexOf(s.when)));
  Object.assign(adoptDlg, {
    open: true,
    card,
    assigned_to: "",
    due_date: latest >= 0 ? dueDateFor(WHEN[latest]) : "",
    target: "",
    error: "",
  });
}
async function adopt() {
  adoptDlg.loading = true;
  adoptDlg.error = "";
  try {
    const target = String(adoptDlg.target ?? "").trim();
    const r = await call(API + "adopt", {
      insight: sug.s.name,
      card: adoptDlg.card?.type,
      assigned_to: adoptDlg.assigned_to,
      due_date: adoptDlg.due_date || undefined,
      target: target || undefined,
    });
    adopted.value = r?.action || "—";
    adoptDlg.open = false;
    await sug.load();
  } catch (e) {
    adoptDlg.error = errText(e);
  } finally {
    adoptDlg.loading = false;
  }
}
function goActions() {
  router.replace({ query: { ...route.query, tab: "actions", issue: undefined } });
}

// --- Reject ---
const rejectDlg = reactive({ open: false, reason: "", note: "", loading: false, error: "" });
function openReject() {
  Object.assign(rejectDlg, { open: true, reason: "", note: "", error: "" });
}
async function reject() {
  rejectDlg.loading = true;
  rejectDlg.error = "";
  try {
    await call(API + "reject", {
      insight: sug.s.name,
      reason: rejectDlg.reason,
      note: rejectDlg.note.trim(),
    });
    rejectDlg.open = false;
    resetPicks();
    await sug.load();
  } catch (e) {
    rejectDlg.error = errText(e);
  } finally {
    rejectDlg.loading = false;
  }
}

// --- Research fixes: preview the exact card, then send ---
const researchReused = ref(false);
const preview = reactive({ open: false, loading: false, sending: false, error: "", data: null as Row | null });
async function loadPreview() {
  preview.loading = true;
  preview.error = "";
  try {
    preview.data = (await call(API + "preview_problem_card", { code: props.code })) || null;
  } catch (e) {
    preview.error = errText(e);
  } finally {
    preview.loading = false;
  }
}
function openPreview() {
  Object.assign(preview, { open: true, data: null, error: "" });
  loadPreview();
}
async function sendResearch() {
  preview.sending = true;
  preview.error = "";
  try {
    const r = await call(API + "request_research", {
      code: props.code,
      regenerate: researchDone.value ? 1 : 0, // "Refresh research" forces a new run
    });
    preview.open = false;
    researchReused.value = !!r?.reused;
    if (r?.insight) await research.load(r.insight);
  } catch (e) {
    preview.error = errText(e);
    emit("refresh-status");
  } finally {
    preview.sending = false;
  }
}

// Load the latest runs the issue already has; start over when the panel switches to another issue.
watch(
  () => [props.code, props.suggestions?.insight, props.research?.insight] as const,
  ([code, sugName, resName], old) => {
    if (old && code !== old[0]) {
      sug.reset();
      research.reset();
      resetPicks();
      adopted.value = "";
      researchReused.value = false;
      Object.assign(sugReq, { error: "", reused: false });
    }
    if (sugName && !sug.s.name) sug.load(sugName);
    if (resName && !research.s.name) research.load(resName);
  },
  { immediate: true }
);

onBeforeUnmount(() => {
  sug.reset();
  research.reset();
});
</script>

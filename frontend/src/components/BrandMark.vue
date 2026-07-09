<script setup lang="ts">
type BrandVariant = 'shell' | 'login'
type BrandTone = 'light' | 'dark'

withDefaults(defineProps<{
  variant?: BrandVariant
  tone?: BrandTone
  ariaLabel?: string
}>(), {
  variant: 'shell',
  tone: 'light',
  ariaLabel: '复盘啦',
})

const uid = `brand-${Math.random().toString(36).slice(2, 10)}`
const bgId = `${uid}-bg`
const glowId = `${uid}-glow`
const redId = `${uid}-red`
</script>

<template>
  <span
    class="brand-mark"
    :class="[`brand-mark--${variant}`, `brand-mark--${tone}`]"
    role="img"
    :aria-label="ariaLabel"
  >
    <svg
      class="brand-mark__svg"
      viewBox="0 0 184 52"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient :id="bgId" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="var(--brand-panel-start)" />
          <stop offset="1" stop-color="var(--brand-panel-end)" />
        </linearGradient>
        <linearGradient :id="redId" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="var(--brand-icon-start)" />
          <stop offset="0.58" stop-color="color-mix(in srgb, var(--brand-icon-start) 72%, var(--brand-icon-end) 28%)" />
          <stop offset="1" stop-color="var(--brand-icon-end)" />
        </linearGradient>
        <filter :id="glowId" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="7" stdDeviation="6" flood-color="var(--brand-icon-start)" flood-opacity="0.22" />
        </filter>
      </defs>

      <rect class="brand-mark__panel" x="0.5" y="0.5" width="183" height="51" rx="15" :fill="`url(#${bgId})`" />
      <path class="brand-mark__panel-line" d="M78 42H175" />
      <path class="brand-mark__signal-fill" d="M116 30L133 20L149 25L166 15L176 18V42H116Z" />
      <path class="brand-mark__signal" d="M116 30L133 20L149 25L166 15L176 18" />

      <g class="brand-mark__icon" :filter="`url(#${glowId})`" transform="translate(8 6)">
        <rect width="40" height="40" rx="12" :fill="`url(#${redId})`" />
        <path d="M9 27L15 20.5L20 23.5L30 13" stroke="#fff7f4" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M28 13H30V15" stroke="#fff7f4" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="15" cy="20.5" r="2.2" fill="#fff7f4" opacity="0.92" />
        <circle cx="20" cy="23.5" r="2" fill="#fff7f4" opacity="0.78" />
      </g>

      <g class="brand-mark__word" transform="translate(59 10) skewX(-6)">
        <text x="0" y="27" class="brand-mark__word-main">复盘啦</text>
      </g>
    </svg>
  </span>
</template>

<style scoped>
.brand-mark {
  --brand-panel-start: rgba(255, 255, 255, 0.72);
  --brand-panel-end: rgba(255, 247, 247, 0.74);
  --brand-line: var(--shell-accent-faint);
  --brand-line-strong: var(--brand-signal);

  display: inline-flex;
  flex: none;
  width: 172px;
  height: 50px;
  color: var(--brand-word);
}

.brand-mark--login {
  width: 184px;
  height: 52px;
}

.brand-mark--shell {
  width: 164px;
  height: 44px;
}

.brand-mark--dark {
  --brand-panel-start: rgba(255, 255, 255, 0.08);
  --brand-panel-end: var(--shell-accent-faint);
}

.brand-mark__svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.brand-mark__panel {
  stroke: rgba(225, 29, 29, 0.08);
}

.brand-mark--shell .brand-mark__panel,
.brand-mark--login .brand-mark__panel {
  fill: transparent;
  stroke: transparent;
}

.brand-mark--shell .brand-mark__panel-line,
.brand-mark--shell .brand-mark__signal-fill,
.brand-mark--login .brand-mark__panel-line,
.brand-mark--login .brand-mark__signal-fill {
  display: none;
}

.brand-mark--shell .brand-mark__icon,
.brand-mark--login .brand-mark__icon {
  filter: drop-shadow(0 3px 8px var(--shell-accent-soft));
}

.brand-mark--shell .brand-mark__word-main,
.brand-mark--login .brand-mark__word-main {
  stroke-width: 0.65px;
}

.brand-mark__panel-line {
  stroke: var(--brand-line);
  stroke-width: 1;
}

.brand-mark__signal-fill {
  fill: rgba(225, 29, 29, 0.06);
}

.brand-mark__signal {
  stroke-linecap: round;
  stroke-linejoin: round;
}

.brand-mark__signal {
  stroke: var(--brand-line-strong);
  stroke-width: 2.2;
}

.brand-mark__word-main {
  font-family: 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', Arial, sans-serif;
  font-size: 27px;
  font-style: italic;
  font-weight: 800;
  letter-spacing: 0;
  stroke-linejoin: round;
  fill: var(--brand-word);
  paint-order: stroke;
  stroke: var(--brand-word-stroke);
  stroke-width: 1.15px;
  filter: drop-shadow(0 1px 1px var(--shell-accent-faint));
}
</style>

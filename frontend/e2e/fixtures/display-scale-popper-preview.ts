import { createApp, defineComponent, h, ref } from 'vue'
import ElementPlus, { ElDatePicker, ElOption, ElSelect, ElTooltip } from 'element-plus'
import 'element-plus/dist/index.css'
import '@/styles/global.css'
import { installElementPlusPopperContainer } from '@/utils/elementPlusPopperContainer'

const Preview = defineComponent({
  setup() {
    const selected = ref('alpha')
    const edgeSelected = ref('alpha')
    const bottomSelected = ref('alpha')
    const date = ref('2026-09-11')
    const edgeDate = ref('2026-09-11')

    function setScale(scale: number) {
      document.documentElement.style.setProperty('--app-display-scale', String(scale))
      document.documentElement.style.setProperty('--app-display-scale-inverse', String(1 / scale))
    }

    return () => h('main', { class: 'popper-preview' }, [
      h('div', { class: 'preview-controls' }, [0.5, 1, 1.5].map((scale) => h('button', {
        'data-testid': `scale-${scale}`,
        onClick: () => setScale(scale),
      }, `${scale * 100}%`))),
      h('label', { class: 'preview-field' }, [
        h('span', '选择器'),
        h(ElSelect, {
          modelValue: selected.value,
          'onUpdate:modelValue': (value: string) => { selected.value = value },
          'data-testid': 'scale-select',
        }, () => [
          h(ElOption, { label: '选项 Alpha', value: 'alpha' }),
          h(ElOption, { label: '选项 Beta', value: 'beta' }),
        ]),
      ]),
      h('output', { 'data-testid': 'select-value' }, selected.value),
      h('label', { class: 'preview-field' }, [
        h('span', '日期'),
        h(ElDatePicker, {
          modelValue: date.value,
          type: 'date',
          format: 'YYYY-MM-DD',
          valueFormat: 'YYYY-MM-DD',
          placement: 'bottom-start',
          fallbackPlacements: ['bottom-start', 'bottom-end'],
          'onUpdate:modelValue': (value: string) => { date.value = value },
          'data-testid': 'scale-date',
        }),
      ]),
      h('output', { 'data-testid': 'date-value' }, date.value),
      h(ElTooltip, { content: '缩放悬浮提示', placement: 'right' }, () => h('button', {
        'data-testid': 'hover-target',
      }, '悬浮提示')),
      h('div', { class: 'edge-select' }, [
        h(ElSelect, {
          modelValue: edgeSelected.value,
          'onUpdate:modelValue': (value: string) => { edgeSelected.value = value },
          'data-testid': 'edge-select',
        }, () => [
          h(ElOption, { label: '边缘选项 Alpha', value: 'alpha' }),
          h(ElOption, { label: '边缘选项 Beta', value: 'beta' }),
        ]),
      ]),
      h(ElDatePicker, {
        class: 'edge-date',
        modelValue: edgeDate.value,
        type: 'date',
        format: 'YYYY-MM-DD',
        valueFormat: 'YYYY-MM-DD',
        placement: 'bottom-start',
        fallbackPlacements: ['bottom-start', 'bottom-end'],
        'onUpdate:modelValue': (value: string) => { edgeDate.value = value },
        'data-testid': 'edge-date',
      }),
      h('div', { class: 'bottom-select' }, [
        h(ElSelect, {
          modelValue: bottomSelected.value,
          'onUpdate:modelValue': (value: string) => { bottomSelected.value = value },
          'data-testid': 'bottom-select',
        }, () => [
          h(ElOption, { label: '底部选项 Alpha', value: 'alpha' }),
          h(ElOption, { label: '底部选项 Beta', value: 'beta' }),
        ]),
      ]),
    ])
  },
})

const style = document.createElement('style')
style.textContent = `
  .popper-preview {
    min-height: 100%;
    padding: 10px 120px;
    background: var(--el-bg-color-page);
    color: var(--el-text-color-primary);
  }
  .preview-controls { display: flex; gap: 8px; margin-bottom: 5px; }
  .preview-field { display: flex; width: 240px; flex-direction: column; gap: 8px; margin-top: 4px; }
  .edge-select { position: absolute; top: 80px; right: 8px; width: 220px; }
  .edge-date { position: absolute; top: 150px; right: 8px; width: 220px !important; }
  .bottom-select { position: absolute; bottom: 8px; left: 120px; width: 220px; }
`
document.head.appendChild(style)

const appRoot = document.querySelector<HTMLElement>('#app')!
createApp(Preview).use(ElementPlus).mount(appRoot)
installElementPlusPopperContainer(appRoot)

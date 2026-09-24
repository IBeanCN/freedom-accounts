<template>
  <el-dialog v-model="visible" title="批量换指纹" width="560px">
    <p class="section-hint">{{ subtitle }}</p>
    <el-form label-position="top">
      <el-form-item label="替换方式">
        <el-select v-model="mode">
          <el-option value="seed_only" label="仅换 seed（其余参数保持不变）" />
          <el-option value="from_template" label="按分组指纹模板重建（seed 随机）" />
          <el-option value="random" label="完全随机（每账号独立随机一套）" />
        </el-select>
      </el-form-item>
      <el-alert
        title="统一采购机型建议先用「按模板重建」拉齐参数，日常轮换用「仅换 seed」。该操作不可撤销。"
        type="warning"
        :closable="false"
      />
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">执行替换</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { appStore } from '@/stores/app'

const props = defineProps({
  modelValue: Boolean,
  accountIds: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
})
const emit = defineEmits(['update:modelValue'])
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const mode = ref('seed_only')
const saving = ref(false)
const group = computed(() => appStore.currentGroupModel)
const count = computed(() => props.selectedCount || appStore.accounts.length)
const subtitle = computed(() => {
  const hasTemplate = Boolean(group.value?.fingerprint_template && Object.keys(group.value.fingerprint_template).length)
  return `将为分组「${group.value?.name || ''}」的 ${count.value} 个账号重写指纹，覆盖现有配置。${hasTemplate ? '该分组已配置指纹模板。' : '该分组尚未配置指纹模板（模板方式将退化为完全随机）。'}`
})

async function submit() {
  const modeLabel = {
    seed_only: '仅换 seed',
    from_template: '按分组模板重建',
    random: '完全随机',
  }[mode.value]
  try {
    await ElMessageBox.confirm(
      `分组内 ${count.value} 个账号的指纹将被覆盖（方式：${modeLabel}），此操作不可撤销。`,
      '确认批量替换指纹',
      { confirmButtonText: '执行替换', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    await appStore.batchRegenerateFingerprints(mode.value, props.accountIds)
    visible.value = false
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}
</script>

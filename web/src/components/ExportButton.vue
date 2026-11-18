<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { downloadExport, saveBlob } from '../api/client'

const props = defineProps<{
  payload: Record<string, unknown>
  filename: string
  disabled?: boolean
}>()

const loading = ref(false)

async function run() {
  if (loading.value) return
  loading.value = true
  try {
    const blob = await downloadExport(props.payload)
    saveBlob(blob, props.filename)
    ElMessage.success('导出已开始')
  } catch (e: any) {
    ElMessage.error(e?.message || '导出失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-button type="primary" plain :loading="loading" :disabled="disabled" @click="run">
    导出 Excel
  </el-button>
</template>

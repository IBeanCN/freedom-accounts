import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import { router } from './router'
import { appStore } from './stores/app'
import './styles/main.css'

const app = createApp(App)

for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

app.use(ElementPlus, { locale: zhCn })
app.use(router)

appStore.initAuth().finally(() => {
  if (!window.location.hash) window.location.hash = appStore.authenticated ? '#/groups' : '#/login'
  app.mount('#app')
})

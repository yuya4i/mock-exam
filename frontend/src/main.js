import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import GeneratePage from './views/GeneratePage.vue'
import DatabasePage from './views/DatabasePage.vue'
import ResultsPage from './views/ResultsPage.vue'
import SettingsPage from './views/SettingsPage.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',         component: GeneratePage, name: 'generate' },
    { path: '/database', component: DatabasePage, name: 'database' },
    { path: '/results',  component: ResultsPage,  name: 'results'  },
    { path: '/settings', component: SettingsPage, name: 'settings' },
  ]
})

const pinia = createPinia()
const app   = createApp(App)

app.use(pinia)
app.use(router)
app.mount('#app')

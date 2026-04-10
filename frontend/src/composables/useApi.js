/**
 * useApi.js
 * axiosをラップした共通APIクライアント。
 * ベースURLはVite環境変数 VITE_API_BASE_URL で切り替え可能。
 */
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL
    ? `${import.meta.env.VITE_API_BASE_URL}/api`
    : '/api',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

// レスポンスインターセプター（エラー正規化）
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const message =
      err.response?.data?.error ||
      err.message ||
      'ネットワークエラーが発生しました。'
    return Promise.reject(new Error(message))
  }
)

export default api

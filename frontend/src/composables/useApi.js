/**
 * useApi.js
 * axiosをラップした共通APIクライアント。
 *
 * - ベースURLは Vite 環境変数 `VITE_API_BASE_URL` で切り替え可能。
 * - APIトークン (任意) は localStorage.apiToken に保存し、
 *   リクエストインターセプターで `Authorization: Bearer <token>` を付与する。
 *   未設定時はヘッダを付けない (ローカル開発のゼロフリクション維持)。
 * - レスポンスインターセプターでサーバーのエラーメッセージを取り出し、
 *   401 の場合は専用メッセージへ置換する。
 */
import axios from 'axios'

export const API_TOKEN_STORAGE_KEY = 'apiToken'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL
    ? `${import.meta.env.VITE_API_BASE_URL}/api`
    : '/api',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

// リクエストインターセプター: 保存済みトークンを Authorization ヘッダに付与。
api.interceptors.request.use((config) => {
  try {
    const token = localStorage.getItem(API_TOKEN_STORAGE_KEY)
    if (token && token.trim()) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token.trim()}`
    }
  } catch (_) {
    // localStorage が使えない環境 (private browsing 等) では素通し。
  }
  return config
})

// レスポンスインターセプター: エラー正規化。401 は専用文言で案内する。
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      return Promise.reject(
        new Error('認証に失敗しました。設定画面で API_TOKEN を確認してください。'),
      )
    }
    const message =
      err.response?.data?.error ||
      err.message ||
      'ネットワークエラーが発生しました。'
    return Promise.reject(new Error(message))
  },
)

export default api

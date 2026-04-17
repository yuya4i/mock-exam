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
// FRONTEND-5: the response interceptors fire an `api-token-cleared`
// CustomEvent on window when they zap the bad token, so the Pinia
// settings store can sync its in-memory ref without polling.
export const API_TOKEN_CLEARED_EVENT = 'api-token-cleared'

function _clearStoredToken() {
  try { localStorage.removeItem(API_TOKEN_STORAGE_KEY) } catch (_) {}
  try {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(API_TOKEN_CLEARED_EVENT))
    }
  } catch (_) {}
}

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
// FRONTEND-5: 401 を受けたら localStorage の token を即削除する。
// 削除しないと「壊れたトークン → 401 → リトライ → 401」の無限ループに
// なるし、リクエスト毎に Authorization ヘッダが付き続けるので失敗を
// 観測した瞬間に reset するのが正しい。
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      _clearStoredToken()
      return Promise.reject(
        new Error(
          '認証に失敗しました。保存していたトークンを破棄しました。' +
          '設定画面から API_TOKEN を再設定してください。',
        ),
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

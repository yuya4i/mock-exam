# リモート GPU 運用 (pi-calc ↔ GPU-PC)

quiz-app の AI 生成は **Ollama** に依存する。GPU は GPU-PC 側にしか無いため、
生成は常に GPU-PC の Ollama (`:11434`) が担う。省電力のため GPU-PC は
アイドル時スリープし、必要時に **Wake-on-LAN (WoL)** で起こす。

## 構成 (現行: アプリは GPU-PC で稼働 / pi-calc はコード保管 + WoL 送信元)

```
                 (同一LAN 192.168.10.0/24)
  pi-calc (常時起動, ARM)                 GPU-PC (Windows + WSL2, スリープ可)
  100.106.108.22                          LAN 192.168.10.22
    │                                       ├─ WSL2: docker (backend/frontend)
    │  ① WoL magic packet ───────────────▶ └─ WSL2: ollama :11434 (0.0.0.0)
    │     (MAC 2C-FD-A1-DE-74-DD 宛)
    │  ② GPU-PC 起動 → WSL/docker/ollama 自動起動
    └─ ③ ブラウザ等で GPU-PC のアプリ/Ollama を利用
```

- **WoL 送信元**: `scripts/wake-gpu.py` (依存なし)。pi-calc から実行。
- **WoL ターゲット**: GPU-PC 物理 NIC `2C-FD-A1-DE-74-DD`
  (要確認: LAN 192.168.10.22 を持つアダプタの MAC であること。
  10G `ASUS XG-C100C` と 2.5G オンボードの 2 枚あるため、
  実際に LAN につながっている方の MAC を使う。)

## 1. WoL 送信 (pi-calc 側 — 設定不要、すぐ使える)

```bash
# pi-calc で
python3 ~/workspace/quiz-app/scripts/wake-gpu.py 2C-FD-A1-DE-74-DD \
  --broadcast 192.168.10.255
```

env で固定しておくと cron / エイリアスから引数なしで叩ける:

```bash
export GPU_MAC=2C-FD-A1-DE-74-DD
export GPU_BROADCAST=192.168.10.255
python3 ~/workspace/quiz-app/scripts/wake-gpu.py
```

> 送信スクリプトは「パケットを投げる」だけ。GPU-PC 側が下記で
> WoL を受けられる状態になっていないと no-op。

## 2. GPU-PC 側 WoL 有効化 (Windows — 一度きりの設定)

### 2-1. BIOS/UEFI
- "Wake on LAN" / "Power On By PCI-E" 系を **Enabled**。
- ASUS マザーなら *Advanced → APM Configuration → Power On By PCIE/PCI*。

### 2-2. Windows NIC 設定 (PowerShell 管理者)
```powershell
# 対象 NIC 名は Get-NetAdapter で確認 (例: "イーサネット 2")
Set-NetAdapterPowerManagement -Name "イーサネット 2" -WakeOnMagicPacket Enabled
# デバイスマネージャ → NIC → 電源管理:
#   「このデバイスで…スタンバイ状態を解除できる」ON
#   「Magic Packet でのみ…」ON
```

### 2-3. Fast Startup を無効化 (重要)
高速スタートアップが ON だと S5(シャットダウン)から WoL で起きないことが多い。
- コントロールパネル → 電源オプション → 電源ボタンの動作 →
  「高速スタートアップを有効にする」の **チェックを外す**。
- スリープ (S3) からの WoL なら必須ではないが、安定する。

## 3. 起床後にサービスを自動起動 (GPU-PC)

WoL で Windows が起きても、WSL2 / docker / ollama が自動で上がらないと
アプリは使えない。以下のいずれか:

- **ollama コンテナ**: `restart: unless-stopped` (compose 既設) + Docker
  Desktop の「ログイン時に起動」。
- **WSL 自動起動**: Windows タスクスケジューラで *スタートアップ時* に
  `wsl -d Ubuntu -u sna -e sh -c "cd ~/workspace/quiz-app && docker compose up -d"`
  を実行する (トリガ: ログオン / システム起動)。
- 補足: WSL はログオンしないと起動しないため、**自動ログオン** か
  Windows サービス化 (例: NSSM で `wsl ...` を常駐) を検討。

## 4. (任意) pi-calc から GPU-PC の Ollama を直接叩く場合

将来 pi-calc 上でアプリを動かす構成にするなら、backend の
`OLLAMA_BASE_URL` を GPU-PC に向ける:

```bash
# pi-calc の .env など
OLLAMA_BASE_URL=http://192.168.10.22:11434     # 同一LAN直
# または Tailscale 経由 (要: WSL/Windows いずれかの tailscale で 11434 到達性)
# OLLAMA_BASE_URL=http://<gpu-pc-tailscale-ip>:11434
```

> ⚠️ 現状 **WSL 内の tailscale は stopped**、かつ WSL は NAT モードのため、
> Tailscale 越しに WSL 内 Ollama へ入るには (a) WSL で `tailscale up` する、
> もしくは (b) Windows 側で `netsh interface portproxy` により
> 11434 を WSL に転送する、のいずれかが要る。同一 LAN なら
> `192.168.10.22:11434` 直が一番手っ取り早い (Ollama は 0.0.0.0 待受済)。

## 5. セキュリティ memo
- Ollama は現在 `0.0.0.0:11434` 待受 = LAN 全体から到達可能。
  信頼 LAN 前提でなければ `OLLAMA_HOST` を Tailscale IP に絞るか
  ファイアウォールで 11434 を制限する (SECURITY.md 方針と整合)。

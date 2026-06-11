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

### 3-1. 寝起きで quiz-app のポートが切れる問題の自動 heal (実装済)

観測された実害: スリープ復帰後、ollama (:11434) は生き残るのに
**quiz-backend (:4321) / frontend (:1234) のホストポートだけ落ちる**
(コンテナは healthy = 内部 :4321 は 200。Docker Desktop の WSL2
port-proxy が resume で再バインドされない既知挙動)。手動だと毎回
`docker compose restart` が要る。

これを **「システム再開」イベントで自動修復**する:

- `scripts/resume-heal.sh` — 冪等 heal。docker 起動待ち → ホスト :4321 を
  プローブ → 200 なら何もしない / それ以外なら `docker compose restart`。
  ログは `~/.cache/quizgpu-resume-heal.log`。
- `scripts/install-resume-task.cmd` — タスク登録 (非管理者 cmd で実行)。
  トリガ = `Microsoft-Windows-Power-Troubleshooter` EventID 1 (system
  resumed)、アクション = `wsl.exe → resume-heal.sh`、`/IT`(ログオン中
  のみ・パスワード保存なし)。

```bat
REM 登録 (GPU-PC の Windows で)
cmd /c %USERPROFILE%\...\quiz-app\scripts\install-resume-task.cmd
REM 手動テスト
schtasks /Run /TN "quizgpu-resume-restart"
REM 確認 (heal ログに新エントリが出れば チェーン成立)
wsl -d Ubuntu -u sna -e tail -5 ~/.cache/quizgpu-resume-heal.log
REM 削除
schtasks /Delete /TN "quizgpu-resume-restart" /F
```

> 注: `install-resume-task.cmd` は GPU-PC 固有値 (`/RU t4k1h`,
> `-d Ubuntu`, `-u sna`, repo パス) をハードコード。別機では編集する。
> WoL → 起床 → このタスクが ~15-60 秒で quiz-app を復旧、という流れ。
> より根本的に直すなら WSL の `networkingMode=mirrored` (§本書末尾の
> 検討メモ参照: resume 耐性 + Tailscale 直結も同時に解決)。

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

## 7. WSL mirrored networking (LAN/tailnet から WSL 内サービスへ到達)

既定の WSL2 は NAT で、WSL 内サービス (quiz-app :1234/:4321, Ollama
:11434) は GPU-PC の localhost からしか見えず、他機 (スマホ/pi-calc)
から `192.168.10.22:xxxx` に入れない (実測 000)。`networkingMode=mirrored`
で WSL を Windows と同じネット名前空間に寄せ、Windows の LAN/Tailscale
IF にそのまま露出させる。

要件: Win11 22H2+ (build 22621+) / 新しめの WSL。本機は Win11 25H2
build 26200 / WSL 2.7.3 で対応。

### 適用手順 (Windows ターミナルで。`wsl --shutdown` は全 WSL を落とすので
### WSL の中からではなく PowerShell/cmd から実行)

1. `C:\Users\<user>\.wslconfig` の `[wsl2]` に追記済:
   ```
   networkingMode=mirrored
   [experimental]
   hostAddressLoopback=true
   ```
   (既存設定はマージ。元は `.wslconfig.bak.*` に退避)

2. ファイアウォール許可 (**管理者 PowerShell**):
   ```powershell
   New-NetFirewallRule -DisplayName "WSL mirrored: quiz-app+ollama" `
     -Direction Inbound -Action Allow -Protocol TCP -LocalPort 1234,4321,11434
   ```

3. WSL 再起動 (PowerShell/cmd):
   ```
   wsl --shutdown
   ```
   ~10 秒待つ。

4. 復帰 + アプリ起動:
   ```
   wsl -d Ubuntu -u sna -e bash -lc "cd ~/workspace/quiz-app && docker compose -f docker-compose.yml up -d"
   ```

5. 確認:
   - WSL 内: `ip -4 addr` に 192.168.10.22 (mirrored) が出る (旧 172.20.x が消える)
   - スマホ: `http://192.168.10.22:1234/`
   - pi-calc: `curl http://192.168.10.22:11434/api/tags`

### 元に戻す
`.wslconfig` を `.bak.*` から復元 → `wsl --shutdown` → 復帰。

### 注意
- Docker Desktop が稼働している前提 (再起動後にコンテナ復帰)。
- mirrored 後は §3-1 の resume-heal の必要性も下がる (port-proxy 経由
  でなくなるため) が、入れておいて害はない。
- pi-calc → Ollama を Tailscale 経由にするなら、Windows か WSL の
  どちらかで Tailscale を起動 (mirrored なら WSL で `tailscale up`
  しても Windows IF 経由で出る)。

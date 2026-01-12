# Theia3D C3D Extractor

Theia3Dが出力したC3Dファイルから関節中心（Joint Centers）と末端点（Endpoints）を抽出してCSV/JSON形式で出力するPythonツール。

## 機能

- **Streamlit GUI**: ブラウザベースのGUIアプリケーション
- **CLI**: コマンドラインインターフェース
  - `inspect`: C3Dファイルの構造調査
  - `export`: 関節中心・末端点のCSV/JSON出力
  - `batch`: 複数ファイルの一括処理

## インストール

```bash
git clone https://github.com/YOUR_USERNAME/theia_c3d_extractor.git
cd theia_c3d_extractor
pip install -r requirements.txt
```

## 使用方法

### Streamlit GUI（推奨）

```bash
streamlit run app.py
```

ブラウザで http://localhost:8501 が開きます。

**機能:**
- 📂 フォルダ選択ボタンでC3Dファイルのあるフォルダを指定
- 📊 Inspect: C3Dファイルの構造を調査
- 📤 Export: 関節中心・末端点を抽出してCSV/JSONダウンロード
- 📈 Visualize: 抽出データの時系列グラフ表示

### CLI

### 1. C3Dファイルの構造を調査

```bash
# 基本的な調査
python cli.py inspect path/to/file.c3d

# JSON形式で出力
python cli.py inspect path/to/file.c3d --json
```

出力例:
```
============================================================
C3D File: path/to/file.c3d
============================================================

[Header Information]
  Point count: 0
  First frame: 1
  Last frame: 1000
  Frame rate: 100.0 Hz
  Scale factor: -1.0

[Available Parameter Groups]
  - POINT
  - ROTATION
  - TRIAL

[ROTATION Group]
  Labels (17 segments):
    - Pelvis
    - RightUpperLeg
    - RightLowerLeg
    ...
```

### 2. 関節中心・末端点の抽出

```bash
# CSV出力（デフォルト）
python cli.py export path/to/file.c3d

# JSON出力
python cli.py export path/to/file.c3d --format json

# 出力ファイル名を指定
python cli.py export path/to/file.c3d --output joints.csv

# 関節中心のみ出力
python cli.py export path/to/file.c3d --joints-only

# 末端点のみ出力
python cli.py export path/to/file.c3d --endpoints-only

# カスタムマッピングを使用
python cli.py export path/to/file.c3d --mapping custom_mapping.yaml
```

### 3. バッチ処理

```bash
# ディレクトリ内の全C3Dファイルを処理
python cli.py batch ./data/

# サブディレクトリも再帰的に処理
python cli.py batch ./data/ --recursive

# 出力先を指定
python cli.py batch ./data/ --output-dir ./output/ --format json
```

### 4. マッピング設定の確認

```bash
python cli.py show-mapping
```

## 出力形式

### CSV

```csv
frame,time,pelvis_center_x,pelvis_center_y,pelvis_center_z,right_hip_x,...
1,0.0,0.123456,0.234567,0.345678,0.111111,...
2,0.01,0.123457,0.234568,0.345679,0.111112,...
```

### JSON

```json
{
  "metadata": {
    "source_file": "path/to/file.c3d",
    "frame_rate": 100.0,
    "n_frames": 1000,
    "units": "meters"
  },
  "frames": [
    {
      "frame": 1,
      "time": 0.0,
      "joint_centers": {
        "pelvis_center": {"x": 0.123456, "y": 0.234567, "z": 0.345678},
        "right_hip": {"x": 0.111111, "y": 0.222222, "z": 0.333333}
      },
      "endpoints": {
        "right_hand_tip": {"x": 0.444444, "y": 0.555555, "z": 0.666666}
      },
      "confidence": {
        "pelvis_center": 0.95,
        "right_hip": 0.92
      }
    }
  ]
}
```

## マッピング設定 (mapping.yaml)

`mapping.yaml`でセグメント名と出力名の対応を定義できる。

### 関節中心のマッピング

```yaml
joint_centers:
  Pelvis: pelvis_center
  RightUpperLeg: right_hip
  LeftUpperLeg: left_hip
  RightLowerLeg: right_knee
  ...
```

### 末端点の設定

```yaml
endpoints:
  right_hand_tip:
    parent_segment: RightHand
    local_offset: [0.0, 0.08, 0.0]  # ローカル座標系でのオフセット (meters)
    fallback_child: null
```

### 末端点の計算方式

1. **ランドマーク検索**: C3D内のPOINT groupからランドマークを探索
2. **ローカルオフセット**: 親セグメントのpose行列 + `local_offset`で計算 (`P_global = R * P_local + T`)
3. **子セグメントfallback**: 子セグメントのoriginを末端点として使用

## 技術詳細

### Theia3D C3Dのデータ構造

- **ROTATION group**: 4x4 pose行列を格納
  - Column-major形式
  - 1信号 = 17 float（16行列要素 + 信頼度）
  - 行列要素順: `[m00, m10, m20, m30, m01, m11, m21, m31, m02, m12, m22, m32, m03, m13, m23, m33]`

### 関節中心の算出

各セグメントの4x4 pose行列から並進ベクトル（右端列の上3要素）を抽出:

```
Pose Matrix (4x4):
| R00 R01 R02 Tx |
| R10 R11 R12 Ty |
| R20 R21 R22 Tz |
|  0   0   0   1 |

Joint Center = [Tx, Ty, Tz]
```

### 末端点の算出

ローカル座標からグローバル座標への変換:

```
P_global = R * P_local + T
```

## モジュール構成

```
theia_c3d_extractor/
├── app.py           # Streamlit GUIアプリケーション
├── cli.py           # CLIインターフェース (typer)
├── inspect_c3d.py   # C3D構造調査モジュール
├── export_joints.py # 関節中心・末端点抽出モジュール
├── mapping.yaml     # セグメント名マッピング設定
├── requirements.txt # 依存パッケージ
├── .gitignore       # Git除外設定
└── README.md        # このファイル
```

## GitHubへのアップロード

```bash
cd theia_c3d_extractor
git init
git add .
git commit -m "Initial commit: Theia3D C3D Extractor"
git remote add origin https://github.com/YOUR_USERNAME/theia_c3d_extractor.git
git push -u origin main
```

## ライセンス

MIT License

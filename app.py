"""
Streamlit GUI for Theia3D C3D Extractor

フォルダからC3Dファイルを選択して、関節中心・末端点を抽出するGUIアプリケーション
"""

import streamlit as st
import pandas as pd
from pathlib import Path
import json
import tempfile
import os

from inspect_c3d import inspect_c3d
from export_joints import JointExtractor, read_rotation_data_direct

# ページ設定
st.set_page_config(
    page_title="Theia3D C3D Extractor",
    page_icon="🦴",
    layout="wide",
)


def is_tkinter_available() -> bool:
    """tkinterが使用可能かチェック"""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.destroy()
        return True
    except Exception:
        return False


def select_folder_dialog() -> str | None:
    """tkinterでフォルダ選択ダイアログを表示（ローカル環境のみ）"""
    import tkinter as tk
    from tkinter import filedialog
    import threading

    result = [None]

    def run_dialog():
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        folder = filedialog.askdirectory(
            title="C3Dファイルが格納されているフォルダを選択"
        )
        result[0] = folder if folder else None
        root.destroy()

    thread = threading.Thread(target=run_dialog)
    thread.start()
    thread.join(timeout=60)

    return result[0]


# 環境検出
TKINTER_AVAILABLE = is_tkinter_available()

# セッション状態の初期化
if 'folder_path' not in st.session_state:
    st.session_state.folder_path = str(Path(__file__).parent) if TKINTER_AVAILABLE else ""
if 'selected_file' not in st.session_state:
    st.session_state.selected_file = None
if 'inspection_result' not in st.session_state:
    st.session_state.inspection_result = None
if 'export_data' not in st.session_state:
    st.session_state.export_data = None
if 'uploaded_file_data' not in st.session_state:
    st.session_state.uploaded_file_data = None
if 'uploaded_file_name' not in st.session_state:
    st.session_state.uploaded_file_name = None


def get_c3d_files(folder_path: str) -> list[Path]:
    """フォルダ内のC3Dファイル一覧を取得"""
    folder = Path(folder_path)
    if not folder.exists():
        return []
    return sorted(folder.glob("*.c3d"))


def format_inspection_result(info: dict) -> None:
    """調査結果を表示"""
    st.subheader("📋 ファイル情報")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**ヘッダー情報**")
        header = info.get('header', {})
        st.text(f"フレーム範囲: {header.get('first_frame')} - {header.get('last_frame')}")
        st.text(f"フレームレート: {header.get('frame_rate')} Hz")
        st.text(f"総フレーム数: {header.get('last_frame', 0) - header.get('first_frame', 0) + 1}")

    with col2:
        st.markdown("**ROTATIONグループ**")
        rotation = info.get('rotation', {})
        st.text(f"セグメント数: {len(rotation.get('labels', []))}")
        st.text(f"レート: {rotation.get('rate')} Hz")

    # セグメント一覧
    st.markdown("**セグメント一覧**")
    labels = info.get('rotation', {}).get('labels', [])
    if labels:
        cols = st.columns(3)
        for i, label in enumerate(labels):
            cols[i % 3].text(f"• {label}")


def create_preview_dataframe(data: dict, max_rows: int = 10) -> pd.DataFrame:
    """プレビュー用のDataFrameを作成"""
    frames = data['frames'][:max_rows]

    rows = []
    for frame in frames:
        row = {
            'frame': frame['frame'],
            'time': frame['time'],
        }
        for name, pos in frame['joint_centers'].items():
            row[f'{name}_x'] = pos['x']
            row[f'{name}_y'] = pos['y']
            row[f'{name}_z'] = pos['z']
        for name, pos in frame['endpoints'].items():
            row[f'{name}_x'] = pos['x']
            row[f'{name}_y'] = pos['y']
            row[f'{name}_z'] = pos['z']
        rows.append(row)

    return pd.DataFrame(rows)


def export_to_csv_string(data: dict) -> str:
    """CSV文字列に変換"""
    frames = data['frames']
    if not frames:
        return ""

    all_joint_keys = set()
    all_endpoint_keys = set()

    for frame in frames:
        all_joint_keys.update(frame['joint_centers'].keys())
        all_endpoint_keys.update(frame['endpoints'].keys())

    all_joint_keys = sorted(all_joint_keys)
    all_endpoint_keys = sorted(all_endpoint_keys)

    header = ['frame', 'time']
    for name in all_joint_keys:
        header.extend([f'{name}_x', f'{name}_y', f'{name}_z'])
    for name in all_endpoint_keys:
        header.extend([f'{name}_x', f'{name}_y', f'{name}_z'])

    lines = [','.join(header)]

    for frame in frames:
        row = [str(frame['frame']), str(frame['time'])]
        for name in all_joint_keys:
            pos = frame['joint_centers'].get(name, {})
            row.extend([
                str(pos.get('x', '')),
                str(pos.get('y', '')),
                str(pos.get('z', '')),
            ])
        for name in all_endpoint_keys:
            pos = frame['endpoints'].get(name, {})
            row.extend([
                str(pos.get('x', '')),
                str(pos.get('y', '')),
                str(pos.get('z', '')),
            ])
        lines.append(','.join(row))

    return '\n'.join(lines)


def process_uploaded_file(uploaded_file) -> Path | None:
    """アップロードされたファイルを一時ファイルに保存"""
    if uploaded_file is None:
        return None

    # 一時ファイルに保存
    with tempfile.NamedTemporaryFile(delete=False, suffix='.c3d') as tmp:
        tmp.write(uploaded_file.getvalue())
        return Path(tmp.name)


def main():
    st.title("🦴 Theia3D C3D Extractor")
    st.markdown("Theia3DのC3Dファイルから関節中心・末端点を抽出します")

    # サイドバー
    st.sidebar.header("📁 ファイル選択")

    selected_file = None
    file_source = None

    if TKINTER_AVAILABLE:
        # ローカル環境: フォルダ選択 + ファイルアップロード両対応
        input_mode = st.sidebar.radio(
            "入力方法",
            ["フォルダから選択", "ファイルをアップロード"],
            index=0
        )

        if input_mode == "フォルダから選択":
            if st.sidebar.button("📂 フォルダを選択...", use_container_width=True):
                selected = select_folder_dialog()
                if selected:
                    st.session_state.folder_path = selected
                    st.session_state.inspection_result = None
                    st.session_state.export_data = None
                    st.rerun()

            folder_path = st.sidebar.text_input(
                "フォルダパス",
                value=st.session_state.folder_path,
                help="C3Dファイルが格納されているフォルダのパス"
            )

            if folder_path != st.session_state.folder_path:
                st.session_state.folder_path = folder_path
                st.session_state.inspection_result = None
                st.session_state.export_data = None

            c3d_files = get_c3d_files(st.session_state.folder_path)

            if c3d_files:
                st.sidebar.success(f"{len(c3d_files)} 個のC3Dファイル")
                file_names = [f.name for f in c3d_files]
                selected_name = st.sidebar.selectbox("ファイルを選択", file_names, index=0)
                selected_file = Path(st.session_state.folder_path) / selected_name
                file_source = "folder"
            else:
                st.sidebar.warning("C3Dファイルが見つかりません")

        else:  # ファイルをアップロード
            uploaded = st.sidebar.file_uploader(
                "C3Dファイルをアップロード",
                type=['c3d'],
                help="Theia3Dで出力したC3Dファイルを選択"
            )
            if uploaded:
                selected_file = process_uploaded_file(uploaded)
                st.session_state.uploaded_file_name = uploaded.name
                file_source = "upload"

    else:
        # クラウド環境: ファイルアップロードのみ
        st.sidebar.info("💡 C3Dファイルをアップロードしてください")

        uploaded = st.sidebar.file_uploader(
            "C3Dファイルをアップロード",
            type=['c3d'],
            help="Theia3Dで出力したC3Dファイルを選択"
        )
        if uploaded:
            selected_file = process_uploaded_file(uploaded)
            st.session_state.uploaded_file_name = uploaded.name
            file_source = "upload"

    if selected_file is None:
        st.info("👈 サイドバーでC3Dファイルを選択またはアップロードしてください")
        return

    # マッピング設定
    st.sidebar.header("⚙️ 設定")
    mapping_path = Path(__file__).parent / 'mapping.yaml'

    output_units = st.sidebar.radio(
        "出力単位",
        ["meters", "millimeters"],
        index=0
    )

    # ファイル名表示
    display_name = st.session_state.uploaded_file_name if file_source == "upload" else selected_file.name

    # メインエリア: タブ
    tab1, tab2, tab3 = st.tabs(["📊 Inspect", "📤 Export", "📈 Visualize"])

    # ========== Inspect タブ ==========
    with tab1:
        st.header("C3Dファイル構造の調査")
        st.caption(f"選択中: `{display_name}`")

        if st.button("🔍 Inspect", key="inspect_btn"):
            with st.spinner("解析中..."):
                try:
                    info = inspect_c3d(selected_file)
                    st.session_state.inspection_result = info
                except Exception as e:
                    st.error(f"エラー: {e}")
                    return

        if st.session_state.inspection_result:
            format_inspection_result(st.session_state.inspection_result)
            with st.expander("📄 生データ (JSON)"):
                st.json(st.session_state.inspection_result)

    # ========== Export タブ ==========
    with tab2:
        st.header("関節中心・末端点の抽出")
        st.caption(f"選択中: `{display_name}`")

        col1, col2 = st.columns(2)
        with col1:
            include_joints = st.checkbox("関節中心を含める", value=True)
        with col2:
            include_endpoints = st.checkbox("末端点を含める", value=True)

        if st.button("🚀 Extract", key="extract_btn"):
            with st.spinner("抽出中..."):
                try:
                    extractor = JointExtractor(mapping_path)
                    extractor.output_units['position'] = output_units

                    data = extractor.extract_from_c3d(selected_file)

                    if not include_joints:
                        for frame in data['frames']:
                            frame['joint_centers'] = {}
                    if not include_endpoints:
                        for frame in data['frames']:
                            frame['endpoints'] = {}

                    st.session_state.export_data = data
                    st.success("抽出完了!")
                except Exception as e:
                    st.error(f"エラー: {e}")
                    return

        if st.session_state.export_data:
            data = st.session_state.export_data

            st.subheader("📋 メタデータ")
            meta = data['metadata']
            col1, col2, col3 = st.columns(3)
            col1.metric("フレーム数", meta['n_frames'])
            col2.metric("フレームレート", f"{meta['frame_rate']} Hz")
            col3.metric("単位", meta['units'])

            st.subheader("👁️ プレビュー (最初の10フレーム)")
            preview_df = create_preview_dataframe(data)
            st.dataframe(preview_df, use_container_width=True)

            st.subheader("💾 ダウンロード")
            col1, col2 = st.columns(2)

            base_name = Path(display_name).stem

            with col1:
                csv_data = export_to_csv_string(data)
                st.download_button(
                    label="📥 CSVダウンロード",
                    data=csv_data,
                    file_name=f"{base_name}_joints.csv",
                    mime="text/csv"
                )

            with col2:
                json_data = json.dumps(data, indent=2, ensure_ascii=False)
                st.download_button(
                    label="📥 JSONダウンロード",
                    data=json_data,
                    file_name=f"{base_name}_joints.json",
                    mime="application/json"
                )

    # ========== Visualize タブ ==========
    with tab3:
        st.header("データの可視化")

        if st.session_state.export_data is None:
            st.info("👆 まず「Export」タブでデータを抽出してください")
            return

        data = st.session_state.export_data

        available_joints = list(data['frames'][0]['joint_centers'].keys()) if data['frames'] else []
        available_endpoints = list(data['frames'][0]['endpoints'].keys()) if data['frames'] else []
        all_points = available_joints + available_endpoints

        if not all_points:
            st.warning("表示可能なデータがありません")
            return

        selected_points = st.multiselect(
            "表示する点を選択",
            all_points,
            default=all_points[:3] if len(all_points) >= 3 else all_points
        )

        axis = st.radio("表示する軸", ["x", "y", "z"], horizontal=True)

        if selected_points:
            chart_data = {'frame': [], 'time': []}
            for point in selected_points:
                chart_data[point] = []

            for frame in data['frames']:
                chart_data['frame'].append(frame['frame'])
                chart_data['time'].append(frame['time'])

                for point in selected_points:
                    if point in frame['joint_centers']:
                        chart_data[point].append(frame['joint_centers'][point][axis])
                    elif point in frame['endpoints']:
                        chart_data[point].append(frame['endpoints'][point][axis])
                    else:
                        chart_data[point].append(None)

            df = pd.DataFrame(chart_data)
            df = df.set_index('time')
            df = df.drop(columns=['frame'])

            st.line_chart(df)

            st.subheader("📊 統計情報")
            stats_df = df.describe()
            st.dataframe(stats_df)


if __name__ == "__main__":
    main()

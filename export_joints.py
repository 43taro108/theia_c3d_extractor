"""
export_joints.py - Theia3D C3Dファイルから関節中心・末端点を抽出してCSV/JSON出力

Theia3DのROTATION groupには4x4 pose行列が格納されている。
- Column-major形式
- 1信号 = 17 float（16行列要素 + 信頼度）
- 関節中心 = 各セグメント座標系のorigin（translation）
- 末端点 = ランドマークのローカル座標をR*P_Sで変換、または子セグメントのoriginをfallback
"""

import csv
import json
from pathlib import Path
from typing import Any

import c3d
import numpy as np
import yaml


def load_mapping(mapping_path: str | Path) -> dict:
    """マッピング設定をYAMLから読み込む"""
    with open(mapping_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def decode_labels(raw_labels: bytes | None, label_width: int = 32) -> list[str]:
    """ラベルバイト列をデコードしてリストに変換"""
    if raw_labels is None:
        return []
    labels = []
    for i in range(0, len(raw_labels), label_width):
        label = raw_labels[i:i + label_width].decode('utf-8', errors='ignore').strip()
        if label:
            labels.append(label)
    return labels


def get_rotation_labels(reader: c3d.Reader) -> list[str]:
    """ROTATION:LABELSを取得"""
    rotation_group = reader.get('ROTATION')
    if rotation_group is None:
        return []

    labels_param = rotation_group.get('LABELS')
    if labels_param is None:
        return []

    raw = labels_param.bytes_value
    dims = labels_param.dimensions
    label_width = dims[0] if dims and len(dims) >= 1 else 32
    return decode_labels(raw, label_width)


def read_rotation_data_direct(filepath: str | Path) -> tuple[np.ndarray, list[str], float, int]:
    """
    C3DファイルからROTATIONデータを直接読み取る

    Returns:
        (data, labels, frame_rate, first_frame)
        data: shape (n_frames, n_segments, 17) - 16要素の行列 + 信頼度
        labels: セグメント名のリスト
        frame_rate: フレームレート
        first_frame: 最初のフレーム番号
    """
    with open(filepath, 'rb') as f:
        reader = c3d.Reader(f)

        # ラベル取得
        labels = get_rotation_labels(reader)
        n_segments = len(labels)

        if n_segments == 0:
            raise ValueError("No ROTATION labels found in C3D file")

        # ROTATIONパラメータを取得
        rotation_group = reader.get('ROTATION')
        data_start = int(rotation_group.get('DATA_START').uint16_value)
        used = int(rotation_group.get('USED').uint16_value)

        # ヘッダー情報
        frame_rate = reader.header.frame_rate
        first_frame = reader.header.first_frame
        last_frame = reader.header.last_frame
        n_frames = last_frame - first_frame + 1

        # ブロックサイズは512バイト
        block_size = 512
        data_offset = (data_start - 1) * block_size

        # 1セグメント = 17 float (16 matrix + 1 confidence)
        floats_per_segment = 17
        floats_per_frame = n_segments * floats_per_segment

        # ファイルを直接読む
        f.seek(data_offset)
        expected_bytes = n_frames * floats_per_frame * 4
        raw_data = f.read(expected_bytes)

        # float32として解釈
        data = np.frombuffer(raw_data, dtype=np.float32)

        # 形状を変換
        expected_floats = n_frames * n_segments * floats_per_segment
        if len(data) >= expected_floats:
            data = data[:expected_floats].reshape(n_frames, n_segments, floats_per_segment)
        else:
            # データが不足している場合
            actual_frames = len(data) // (n_segments * floats_per_segment)
            if actual_frames > 0:
                data = data[:actual_frames * n_segments * floats_per_segment].reshape(
                    actual_frames, n_segments, floats_per_segment
                )
                n_frames = actual_frames
            else:
                raise ValueError(f"Insufficient rotation data: got {len(data)} floats, expected {expected_floats}")

    return data, labels, frame_rate, first_frame


def extract_pose_matrix(segment_data: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """
    17要素のセグメントデータから4x4 pose行列を抽出

    Args:
        segment_data: shape (17,) - 16行列要素 + 信頼度

    Returns:
        (rotation_matrix, translation, confidence)
        rotation_matrix: 3x3回転行列
        translation: 3要素の並進ベクトル（関節中心）
        confidence: 信頼度
    """
    # Column-major形式で格納された4x4行列を復元
    matrix_elements = segment_data[:16]
    confidence = segment_data[16] if len(segment_data) > 16 else 1.0

    # Column-major -> 4x4行列
    pose_matrix = matrix_elements.reshape(4, 4, order='F')

    # 回転行列（左上3x3）と並進（4列目の上3要素）を抽出
    rotation_matrix = pose_matrix[:3, :3]
    translation = pose_matrix[:3, 3]

    return rotation_matrix, translation, confidence


def transform_local_to_global(
    rotation_matrix: np.ndarray,
    translation: np.ndarray,
    local_point: np.ndarray
) -> np.ndarray:
    """
    ローカル座標をグローバル座標に変換

    P_global = R * P_local + T

    Args:
        rotation_matrix: 3x3回転行列
        translation: 3要素の並進ベクトル
        local_point: ローカル座標 (3要素)

    Returns:
        グローバル座標 (3要素)
    """
    return rotation_matrix @ local_point + translation


class JointExtractor:
    """関節中心・末端点の抽出器"""

    def __init__(self, mapping_path: str | Path):
        self.mapping = load_mapping(mapping_path)
        self.joint_centers_map = self.mapping.get('joint_centers', {})
        self.endpoints_config = self.mapping.get('endpoints', {})
        self.segment_hierarchy = self.mapping.get('segment_hierarchy', {})
        self.output_units = self.mapping.get('output_units', {})

    def extract_from_c3d(self, filepath: str | Path) -> dict:
        """
        C3Dファイルから関節中心と末端点を抽出

        Returns:
            {
                'metadata': {...},
                'frames': [
                    {
                        'frame': int,
                        'time': float,
                        'joint_centers': {...},
                        'endpoints': {...},
                        'confidence': {...}
                    },
                    ...
                ]
            }
        """
        filepath = Path(filepath)

        # ROTATIONデータを読み取り
        rotation_data, labels, frame_rate, first_frame = read_rotation_data_direct(filepath)
        n_frames = rotation_data.shape[0]
        n_segments = rotation_data.shape[1]

        # セグメント名からインデックスへのマッピング
        segment_to_idx = {name: idx for idx, name in enumerate(labels)}

        # 単位はメートル（Theia3Dのデフォルト）
        # 出力単位に応じてスケーリング
        scale_factor = 1.0
        if self.output_units.get('position') == 'millimeters':
            scale_factor = 1000.0

        # フレームデータを処理
        frames_result = []

        for frame_idx in range(n_frames):
            frame_num = first_frame + frame_idx
            time_sec = frame_idx / frame_rate

            frame_data = {
                'frame': int(frame_num),
                'time': round(time_sec, 6),
                'joint_centers': {},
                'endpoints': {},
                'confidence': {},
            }

            # 全セグメントのpose行列をキャッシュ
            segment_poses = {}
            for seg_name, seg_idx in segment_to_idx.items():
                seg_data = rotation_data[frame_idx, seg_idx, :]
                if not np.isnan(seg_data).any():
                    R, T, conf = extract_pose_matrix(seg_data)
                    segment_poses[seg_name] = (R, T, conf)

            # 関節中心の抽出
            for segment_name, output_name in self.joint_centers_map.items():
                if segment_name in segment_poses:
                    R, T, conf = segment_poses[segment_name]
                    T_scaled = T * scale_factor

                    frame_data['joint_centers'][output_name] = {
                        'x': round(float(T_scaled[0]), 6),
                        'y': round(float(T_scaled[1]), 6),
                        'z': round(float(T_scaled[2]), 6),
                    }
                    frame_data['confidence'][output_name] = round(float(conf), 4)

            # 末端点の抽出
            for endpoint_name, config in self.endpoints_config.items():
                parent_segment = config.get('parent_segment')
                local_offset = config.get('local_offset')
                fallback_child = config.get('fallback_child')

                endpoint_pos = None
                conf = 0.0

                # 方式1: 親セグメントのpose行列 + ローカルオフセット
                if parent_segment and local_offset and parent_segment in segment_poses:
                    R, T, conf = segment_poses[parent_segment]
                    local_pt = np.array(local_offset)
                    endpoint_pos = transform_local_to_global(R, T, local_pt)

                # 方式2: 子セグメントのoriginをfallback
                if endpoint_pos is None and fallback_child and fallback_child in segment_poses:
                    R, T, conf = segment_poses[fallback_child]
                    endpoint_pos = T

                # 方式3: segment_hierarchyからfallback
                if endpoint_pos is None and parent_segment:
                    child_segment = self.segment_hierarchy.get(parent_segment)
                    if child_segment and child_segment in segment_poses:
                        R, T, conf = segment_poses[child_segment]
                        endpoint_pos = T

                if endpoint_pos is not None:
                    endpoint_pos_scaled = endpoint_pos * scale_factor
                    frame_data['endpoints'][endpoint_name] = {
                        'x': round(float(endpoint_pos_scaled[0]), 6),
                        'y': round(float(endpoint_pos_scaled[1]), 6),
                        'z': round(float(endpoint_pos_scaled[2]), 6),
                    }
                    frame_data['confidence'][endpoint_name] = round(float(conf), 4)

            frames_result.append(frame_data)

        # メタデータ
        metadata = {
            'source_file': str(filepath),
            'frame_rate': float(frame_rate),
            'n_frames': n_frames,
            'first_frame': int(first_frame),
            'segments': labels,
            'units': self.output_units.get('position', 'meters'),
        }

        return {
            'metadata': metadata,
            'frames': frames_result,
        }

    def export_to_json(self, data: dict, output_path: str | Path) -> None:
        """JSON形式で出力"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def export_to_csv(self, data: dict, output_path: str | Path) -> None:
        """CSV形式で出力（フラット化）"""
        frames = data['frames']
        if not frames:
            return

        # 全フレームから全てのキーを収集
        all_joint_keys = set()
        all_endpoint_keys = set()
        all_confidence_keys = set()

        for frame in frames:
            all_joint_keys.update(frame['joint_centers'].keys())
            all_endpoint_keys.update(frame['endpoints'].keys())
            all_confidence_keys.update(frame['confidence'].keys())

        all_joint_keys = sorted(all_joint_keys)
        all_endpoint_keys = sorted(all_endpoint_keys)
        all_confidence_keys = sorted(all_confidence_keys)

        # ヘッダーを構築
        header = ['frame', 'time']

        # 関節中心のカラム
        for joint_name in all_joint_keys:
            header.extend([f'{joint_name}_x', f'{joint_name}_y', f'{joint_name}_z'])

        # 末端点のカラム
        for endpoint_name in all_endpoint_keys:
            header.extend([f'{endpoint_name}_x', f'{endpoint_name}_y', f'{endpoint_name}_z'])

        # 信頼度のカラム
        for name in all_confidence_keys:
            header.append(f'{name}_confidence')

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)

            for frame in frames:
                row = [frame['frame'], frame['time']]

                # 関節中心
                for joint_name in all_joint_keys:
                    pos = frame['joint_centers'].get(joint_name, {})
                    row.extend([
                        pos.get('x', ''),
                        pos.get('y', ''),
                        pos.get('z', ''),
                    ])

                # 末端点
                for endpoint_name in all_endpoint_keys:
                    pos = frame['endpoints'].get(endpoint_name, {})
                    row.extend([
                        pos.get('x', ''),
                        pos.get('y', ''),
                        pos.get('z', ''),
                    ])

                # 信頼度
                for name in all_confidence_keys:
                    row.append(frame['confidence'].get(name, ''))

                writer.writerow(row)


def export_joints(
    c3d_path: str | Path,
    output_path: str | Path,
    mapping_path: str | Path | None = None,
    output_format: str = 'csv'
) -> None:
    """
    関節中心・末端点を抽出してファイルに出力

    Args:
        c3d_path: 入力C3Dファイルのパス
        output_path: 出力ファイルのパス
        mapping_path: マッピングYAMLファイルのパス（省略時はデフォルト）
        output_format: 出力形式 ('csv' or 'json')
    """
    if mapping_path is None:
        mapping_path = Path(__file__).parent / 'mapping.yaml'

    extractor = JointExtractor(mapping_path)
    data = extractor.extract_from_c3d(c3d_path)

    output_path = Path(output_path)
    if output_format.lower() == 'json':
        extractor.export_to_json(data, output_path)
    else:
        extractor.export_to_csv(data, output_path)


def main(c3d_path: str, output_path: str, output_format: str = 'csv') -> None:
    """メイン実行関数"""
    export_joints(c3d_path, output_path, output_format=output_format)
    print(f"Exported to: {output_path}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python export_joints.py <input.c3d> <output.csv|json> [format]")
        sys.exit(1)

    c3d_file = sys.argv[1]
    output_file = sys.argv[2]
    fmt = sys.argv[3] if len(sys.argv) > 3 else 'csv'
    main(c3d_file, output_file, fmt)

"""
inspect_c3d.py - Theia3D C3Dファイルの構造を調査するモジュール

ROTATION:LABELSと利用可能なランドマーク/point系ラベル、単位を表示する。
"""

from pathlib import Path
from typing import Any

import c3d
import numpy as np


def get_parameter_value(reader: c3d.Reader, group: str, param: str) -> Any | None:
    """パラメータ値を安全に取得する"""
    try:
        group_obj = reader.get(group)
        if group_obj is None:
            return None
        param_obj = group_obj.get(param)
        if param_obj is None:
            return None
        return param_obj.bytes_value if hasattr(param_obj, 'bytes_value') else param_obj
    except (KeyError, AttributeError):
        return None


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


def inspect_rotation_group(reader: c3d.Reader) -> dict:
    """ROTATION groupの情報を抽出"""
    info = {
        'labels': [],
        'rate': None,
        'frames': None,
        'data_shape': None,
    }

    # ROTATION:LABELS
    rotation_group = reader.get('ROTATION')
    if rotation_group is None:
        return info

    labels_param = rotation_group.get('LABELS')
    if labels_param is not None:
        # ラベルの取得
        raw = labels_param.bytes_value
        dims = labels_param.dimensions
        if dims and len(dims) >= 1:
            label_width = dims[0]
            info['labels'] = decode_labels(raw, label_width)

    # RATE
    rate_param = rotation_group.get('RATE')
    if rate_param is not None:
        try:
            info['rate'] = rate_param.float_value
        except:
            pass

    # FRAMES
    frames_param = rotation_group.get('FRAMES')
    if frames_param is not None:
        try:
            info['frames'] = int(frames_param.uint16_value) if hasattr(frames_param, 'uint16_value') else None
        except:
            pass

    return info


def inspect_point_group(reader: c3d.Reader) -> dict:
    """POINT groupの情報を抽出"""
    info = {
        'labels': [],
        'rate': None,
        'frames': None,
        'units': None,
        'scale': None,
    }

    point_group = reader.get('POINT')
    if point_group is None:
        return info

    # LABELS
    labels_param = point_group.get('LABELS')
    if labels_param is not None:
        raw = labels_param.bytes_value
        dims = labels_param.dimensions
        if dims and len(dims) >= 1:
            label_width = dims[0]
            info['labels'] = decode_labels(raw, label_width)

    # RATE
    rate_param = point_group.get('RATE')
    if rate_param is not None:
        try:
            info['rate'] = rate_param.float_value
        except:
            pass

    # FRAMES
    frames_param = point_group.get('FRAMES')
    if frames_param is not None:
        try:
            info['frames'] = int(frames_param.uint16_value)
        except:
            pass

    # UNITS
    units_param = point_group.get('UNITS')
    if units_param is not None:
        try:
            info['units'] = units_param.bytes_value.decode('utf-8', errors='ignore').strip()
        except:
            pass

    # SCALE
    scale_param = point_group.get('SCALE')
    if scale_param is not None:
        try:
            info['scale'] = scale_param.float_value
        except:
            pass

    return info


def inspect_available_groups(reader: c3d.Reader) -> list[str]:
    """利用可能なグループ一覧を取得"""
    groups = []
    for gid, group in reader.group_items():
        if not group.name.startswith('_'):
            groups.append(group.name)
    return sorted(groups)


def inspect_segment_landmarks(reader: c3d.Reader) -> dict:
    """セグメントランドマーク情報を抽出（存在する場合）"""
    info = {}

    # SEGMENT groupを探す
    segment_group = reader.get('SEGMENT')
    if segment_group is None:
        return info

    for param_name, param in segment_group.param_items():
        if param_name.startswith('_'):
            continue
        try:
            info[param_name] = {
                'dimensions': param.dimensions,
                'type': str(type(param).__name__),
            }
        except:
            pass

    return info


def get_trial_info(reader: c3d.Reader) -> dict:
    """TRIALグループから試行情報を取得"""
    info = {
        'start_frame': None,
        'end_frame': None,
    }

    trial_group = reader.get('TRIAL')
    if trial_group is None:
        return info

    start_param = trial_group.get('ACTUAL_START_FIELD')
    if start_param is not None:
        try:
            info['start_frame'] = int(start_param.uint16_value)
        except:
            pass

    end_param = trial_group.get('ACTUAL_END_FIELD')
    if end_param is not None:
        try:
            info['end_frame'] = int(end_param.uint16_value)
        except:
            pass

    return info


def inspect_c3d(filepath: str | Path) -> dict:
    """
    C3Dファイルを調査して構造情報を返す

    Args:
        filepath: C3Dファイルのパス

    Returns:
        構造情報を含む辞書
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"C3D file not found: {filepath}")

    result = {
        'filepath': str(filepath),
        'available_groups': [],
        'rotation': {},
        'point': {},
        'segment_landmarks': {},
        'trial': {},
    }

    with open(filepath, 'rb') as f:
        reader = c3d.Reader(f)

        result['available_groups'] = inspect_available_groups(reader)
        result['rotation'] = inspect_rotation_group(reader)
        result['point'] = inspect_point_group(reader)
        result['segment_landmarks'] = inspect_segment_landmarks(reader)
        result['trial'] = get_trial_info(reader)

        # ヘッダー情報
        result['header'] = {
            'point_count': reader.header.point_count,
            'analog_count': reader.header.analog_count,
            'first_frame': reader.header.first_frame,
            'last_frame': reader.header.last_frame,
            'frame_rate': reader.header.frame_rate,
            'scale_factor': reader.header.scale_factor,
        }

    return result


def print_inspection_report(info: dict) -> None:
    """調査結果を整形して表示"""
    print("=" * 60)
    print(f"C3D File: {info['filepath']}")
    print("=" * 60)

    # Header info
    print("\n[Header Information]")
    header = info.get('header', {})
    print(f"  Point count: {header.get('point_count', 'N/A')}")
    print(f"  First frame: {header.get('first_frame', 'N/A')}")
    print(f"  Last frame: {header.get('last_frame', 'N/A')}")
    print(f"  Frame rate: {header.get('frame_rate', 'N/A')} Hz")
    print(f"  Scale factor: {header.get('scale_factor', 'N/A')}")

    # Available groups
    print("\n[Available Parameter Groups]")
    for grp in info.get('available_groups', []):
        print(f"  - {grp}")

    # ROTATION group
    print("\n[ROTATION Group]")
    rotation = info.get('rotation', {})
    labels = rotation.get('labels', [])
    print(f"  Labels ({len(labels)} segments):")
    for label in labels:
        print(f"    - {label}")
    if rotation.get('rate'):
        print(f"  Rate: {rotation['rate']} Hz")
    if rotation.get('frames'):
        print(f"  Frames: {rotation['frames']}")

    # POINT group
    print("\n[POINT Group (Landmarks/Markers)]")
    point = info.get('point', {})
    point_labels = point.get('labels', [])
    print(f"  Labels ({len(point_labels)} points):")
    for label in point_labels[:20]:  # 最初の20個のみ表示
        print(f"    - {label}")
    if len(point_labels) > 20:
        print(f"    ... and {len(point_labels) - 20} more")
    if point.get('units'):
        print(f"  Units: {point['units']}")
    if point.get('rate'):
        print(f"  Rate: {point['rate']} Hz")
    if point.get('scale'):
        print(f"  Scale: {point['scale']}")

    # Segment landmarks
    if info.get('segment_landmarks'):
        print("\n[SEGMENT Group Parameters]")
        for name, data in info['segment_landmarks'].items():
            print(f"  - {name}: dims={data.get('dimensions')}")

    # Trial info
    trial = info.get('trial', {})
    if trial.get('start_frame') or trial.get('end_frame'):
        print("\n[Trial Information]")
        print(f"  Actual start: {trial.get('start_frame', 'N/A')}")
        print(f"  Actual end: {trial.get('end_frame', 'N/A')}")

    print("\n" + "=" * 60)


def main(filepath: str) -> None:
    """メイン実行関数"""
    info = inspect_c3d(filepath)
    print_inspection_report(info)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python inspect_c3d.py <path_to_c3d_file>")
        sys.exit(1)
    main(sys.argv[1])

"""
Theia3D C3D Extractor

Theia3Dが出力したC3Dファイルから関節中心・末端点を抽出するツール
"""

from .inspect_c3d import inspect_c3d, print_inspection_report
from .export_joints import JointExtractor, export_joints

__version__ = "1.0.0"
__all__ = [
    "inspect_c3d",
    "print_inspection_report",
    "JointExtractor",
    "export_joints",
]

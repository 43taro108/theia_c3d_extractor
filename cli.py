"""
cli.py - Theia3D C3D抽出ツールのCLIインターフェース

typerを使用したサブコマンド:
  - inspect: C3Dファイルの構造を調査
  - export: 関節中心・末端点をCSV/JSON出力
"""

from pathlib import Path
from typing import Optional

import typer

from inspect_c3d import inspect_c3d, print_inspection_report
from export_joints import JointExtractor, export_joints

app = typer.Typer(
    name="theia-c3d",
    help="Theia3D C3Dファイルから関節中心・末端点を抽出するツール",
    add_completion=False,
)


@app.command()
def inspect(
    c3d_file: Path = typer.Argument(
        ...,
        help="調査するC3Dファイルのパス",
        exists=True,
        readable=True,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="JSON形式で出力",
    ),
) -> None:
    """
    C3Dファイルの構造を調査して表示する。

    ROTATION:LABELS、POINT:LABELS、単位情報などを確認できる。
    """
    try:
        info = inspect_c3d(c3d_file)

        if json_output:
            import json
            print(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            print_inspection_report(info)

    except FileNotFoundError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Error reading C3D file: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def export(
    c3d_file: Path = typer.Argument(
        ...,
        help="入力C3Dファイルのパス",
        exists=True,
        readable=True,
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="出力ファイルのパス（省略時は入力ファイル名に基づいて自動生成）",
    ),
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="出力形式 (csv または json)",
    ),
    mapping: Optional[Path] = typer.Option(
        None,
        "--mapping",
        "-m",
        help="マッピングYAMLファイルのパス（省略時はデフォルト）",
        exists=True,
        readable=True,
    ),
    joints_only: bool = typer.Option(
        False,
        "--joints-only",
        help="関節中心のみを出力（末端点を除外）",
    ),
    endpoints_only: bool = typer.Option(
        False,
        "--endpoints-only",
        help="末端点のみを出力（関節中心を除外）",
    ),
) -> None:
    """
    C3Dファイルから関節中心・末端点を抽出してCSV/JSONに出力する。

    Theia3DのROTATION groupに格納された4x4 pose行列から、
    各セグメントの関節中心（translation）と末端点を計算する。
    """
    # 出力形式の検証
    format_lower = format.lower()
    if format_lower not in ('csv', 'json'):
        typer.secho(
            f"Error: Invalid format '{format}'. Use 'csv' or 'json'.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    # 出力パスの決定
    if output is None:
        suffix = '.json' if format_lower == 'json' else '.csv'
        output = c3d_file.with_suffix(suffix)

    # マッピングパスの決定
    if mapping is None:
        mapping = Path(__file__).parent / 'mapping.yaml'

    try:
        typer.echo(f"Processing: {c3d_file}")

        extractor = JointExtractor(mapping)
        data = extractor.extract_from_c3d(c3d_file)

        # フィルタリング
        if joints_only:
            for frame in data['frames']:
                frame['endpoints'] = {}
                frame['confidence'] = {
                    k: v for k, v in frame['confidence'].items()
                    if k in frame['joint_centers']
                }
        elif endpoints_only:
            for frame in data['frames']:
                frame['joint_centers'] = {}
                frame['confidence'] = {
                    k: v for k, v in frame['confidence'].items()
                    if k in frame['endpoints']
                }

        # 出力
        if format_lower == 'json':
            extractor.export_to_json(data, output)
        else:
            extractor.export_to_csv(data, output)

        n_frames = len(data['frames'])
        n_joints = len(data['frames'][0]['joint_centers']) if n_frames > 0 else 0
        n_endpoints = len(data['frames'][0]['endpoints']) if n_frames > 0 else 0

        typer.secho(f"Exported: {output}", fg=typer.colors.GREEN)
        typer.echo(f"  Frames: {n_frames}")
        typer.echo(f"  Joint centers: {n_joints}")
        typer.echo(f"  Endpoints: {n_endpoints}")

    except FileNotFoundError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def batch(
    input_dir: Path = typer.Argument(
        ...,
        help="C3Dファイルが格納されたディレクトリ",
        exists=True,
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="出力ディレクトリ（省略時は入力と同じ場所）",
    ),
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="出力形式 (csv または json)",
    ),
    mapping: Optional[Path] = typer.Option(
        None,
        "--mapping",
        "-m",
        help="マッピングYAMLファイルのパス",
        exists=True,
        readable=True,
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        "-r",
        help="サブディレクトリも再帰的に処理",
    ),
) -> None:
    """
    ディレクトリ内の全C3Dファイルを一括処理する。
    """
    if output_dir is None:
        output_dir = input_dir

    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    if mapping is None:
        mapping = Path(__file__).parent / 'mapping.yaml'

    # C3Dファイルを検索
    pattern = '**/*.c3d' if recursive else '*.c3d'
    c3d_files = list(input_dir.glob(pattern))

    if not c3d_files:
        typer.secho("No C3D files found.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    typer.echo(f"Found {len(c3d_files)} C3D file(s)")

    success_count = 0
    error_count = 0

    for c3d_file in c3d_files:
        try:
            # 出力パスの決定
            relative = c3d_file.relative_to(input_dir)
            suffix = '.json' if format.lower() == 'json' else '.csv'
            output_file = output_dir / relative.with_suffix(suffix)

            # 出力ディレクトリの作成
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # 処理
            export_joints(c3d_file, output_file, mapping, format)
            typer.echo(f"  [OK] {c3d_file.name} -> {output_file.name}")
            success_count += 1

        except Exception as e:
            typer.secho(f"  [ERROR] {c3d_file.name}: {e}", fg=typer.colors.RED)
            error_count += 1

    typer.echo("")
    typer.secho(f"Completed: {success_count} success, {error_count} errors",
                fg=typer.colors.GREEN if error_count == 0 else typer.colors.YELLOW)


@app.command()
def show_mapping(
    mapping: Optional[Path] = typer.Option(
        None,
        "--mapping",
        "-m",
        help="マッピングYAMLファイルのパス",
        exists=True,
        readable=True,
    ),
) -> None:
    """
    現在のマッピング設定を表示する。
    """
    import yaml

    if mapping is None:
        mapping = Path(__file__).parent / 'mapping.yaml'

    with open(mapping, 'r', encoding='utf-8') as f:
        content = yaml.safe_load(f)

    typer.echo("=" * 50)
    typer.echo("Joint Center Mapping (Segment -> Output Name)")
    typer.echo("=" * 50)
    for segment, output in content.get('joint_centers', {}).items():
        typer.echo(f"  {segment:20s} -> {output}")

    typer.echo("")
    typer.echo("=" * 50)
    typer.echo("Endpoint Configuration")
    typer.echo("=" * 50)
    for name, config in content.get('endpoints', {}).items():
        parent = config.get('parent_segment', 'N/A')
        offset = config.get('local_offset', 'N/A')
        typer.echo(f"  {name}:")
        typer.echo(f"    Parent: {parent}")
        typer.echo(f"    Local offset: {offset}")


def main() -> None:
    """エントリーポイント"""
    app()


if __name__ == "__main__":
    main()

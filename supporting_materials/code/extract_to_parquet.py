"""Extract competition workbook data into typed-neutral Parquet files.

The original workbooks are read-only inputs. Values are preserved as text so
that cleaning decisions remain explicit in the downstream preprocessing step.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable

import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq
import xlrd


XLSX_SOURCES = {
    "2.2019.3-2025.3住院门诊人数及超声检查数.xlsx": ("数据", "daily_counts.parquet"),
    "3.2019.3-2025.3住院超声明细.xlsx": ("数据", "inpatient.parquet"),
    "4.2019.3-2025.3体检超声明细.xlsx": ("数据", "physical_exam.parquet"),
    "5.2019.3-2025.3门诊超声明细.xlsx": ("数据", "outpatient.parquet"),
    "6.2019.3-2025.3检查医生工作时间.xlsx": ("数据", "doctor_day.parquet"),
    "7.序号3-序号5数据中的机器ID对应表.xlsx": ("Sheet1", "machine_map.parquet"),
}

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = ROOT / "C题数据"
DEFAULT_OUTPUT_DIR = ROOT / "supporting_materials" / "processed_data" / "raw_parquet"


def to_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def write_batches(
    rows: Iterable[tuple[Any, ...]],
    headers: list[Any],
    output_path: Path,
    first_source_row: int,
    chunk_size: int,
) -> int:
    selected = [(index, str(name).strip()) for index, name in enumerate(headers) if name]
    names = ["source_row", *(name for _, name in selected)]
    schema = pa.schema([pa.field("source_row", pa.int64()), *[pa.field(name, pa.string()) for name in names[1:]]])
    writer = pq.ParquetWriter(output_path, schema=schema, compression="snappy")
    batch: list[dict[str, Any]] = []
    written = 0
    try:
        for offset, values in enumerate(rows):
            if not any(value not in (None, "") for value in values):
                continue
            record: dict[str, Any] = {"source_row": first_source_row + offset}
            for index, name in selected:
                record[name] = to_text(values[index]) if index < len(values) else None
            batch.append(record)
            if len(batch) >= chunk_size:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                written += len(batch)
                batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
            written += len(batch)
    finally:
        writer.close()
    return written


def extract_xlsx(path: Path, sheet_name: str, output_path: Path, chunk_size: int) -> int:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet_name]
    iterator = worksheet.iter_rows(values_only=True)
    headers = list(next(iterator))
    next(iterator)  # field-description row
    try:
        return write_batches(iterator, headers, output_path, first_source_row=3, chunk_size=chunk_size)
    finally:
        workbook.close()


def extract_xls(path: Path, output_path: Path, chunk_size: int) -> int:
    workbook = xlrd.open_workbook(path, on_demand=True, formatting_info=False)
    worksheet = workbook.sheet_by_index(0)
    headers = [worksheet.cell_value(0, column) for column in range(worksheet.ncols)]

    def rows() -> Iterable[tuple[Any, ...]]:
        for row in range(2, worksheet.nrows):
            yield tuple(worksheet.cell_value(row, column) for column in range(worksheet.ncols))

    try:
        return write_batches(rows(), headers, output_path, first_source_row=3, chunk_size=chunk_size)
    finally:
        workbook.release_resources()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--chunk-size", type=int, default=50_000)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    equipment_source = args.input_dir / "1.各彩超诊室设备及检查项目列表.xls"
    equipment_output = args.output_dir / "equipment_capability.parquet"
    count = extract_xls(equipment_source, equipment_output, args.chunk_size)
    print(f"{equipment_source.name}: {count:,} rows -> {equipment_output}", flush=True)

    for filename, (sheet_name, output_name) in XLSX_SOURCES.items():
        source = args.input_dir / filename
        output = args.output_dir / output_name
        count = extract_xlsx(source, sheet_name, output, args.chunk_size)
        print(f"{source.name}: {count:,} rows -> {output}", flush=True)


if __name__ == "__main__":
    main()

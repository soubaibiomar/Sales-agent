"""
Automated validation of Security Controls Traceability for Step 01.
Verifies all 70 baseline controls (01-70) and 12 SAI extension controls (SAI-01-12),
and checks the integrity of references/70-security.xlsx.
"""
import re
from pathlib import Path
import openpyxl
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MAPPING_FILE = REPO_ROOT / "security" / "control-mapping.md"
EXCEL_FILE = REPO_ROOT / "references" / "70-security.xlsx"

def test_control_mapping_file_exists():
    assert MAPPING_FILE.exists(), f"Control mapping file missing: {MAPPING_FILE}"

def test_excel_workbook_integrity():
    assert EXCEL_FILE.exists(), f"Original Excel workbook missing: {EXCEL_FILE}"
    wb = openpyxl.load_workbook(str(EXCEL_FILE), data_only=False)
    assert "Contrôles 01-70" in wb.sheetnames, "Sheet 'Contrôles 01-70' missing in workbook"
    sheet = wb["Contrôles 01-70"]
    
    # Verify row range 8 to 77 (70 controls)
    assert sheet.max_row >= 77, f"Expected at least 77 rows in Excel sheet, got {sheet.max_row}"
    
    control_ids = []
    p0_count = 0
    p1_count = 0
    p2_count = 0
    non_verifie_count = 0
    
    for row in range(8, 78):
        cid = str(sheet.cell(row, 1).value).strip().zfill(2)
        control_ids.append(cid)
        priority = sheet.cell(row, 5).value
        status = sheet.cell(row, 8).value
        
        if priority == "P0":
            p0_count += 1
        elif priority == "P1":
            p1_count += 1
        elif priority == "P2":
            p2_count += 1
            
        if status == "NON VERIFIE":
            non_verifie_count += 1

    assert len(control_ids) == 70, f"Expected exactly 70 control IDs, found {len(control_ids)}"
    assert p0_count == 35, f"Expected 35 P0 controls in original workbook, found {p0_count}"
    assert p1_count == 24, f"Expected 24 P1 controls in original workbook, found {p1_count}"
    assert p2_count == 11, f"Expected 11 P2 controls in original workbook, found {p2_count}"
    assert non_verifie_count == 70, f"Expected all 70 controls to be 'NON VERIFIE', found {non_verifie_count}"

def test_baseline_controls_traceability_in_mapping():
    content = MAPPING_FILE.read_text(encoding="utf-8")
    
    # Find all table rows starting with | **01** ... | **70**
    found_ids = set()
    for row in content.splitlines():
        match = re.match(r"^\|\s*\*\*(\d{2})\*\*\s*\|", row.strip())
        if match:
            cid = match.group(1)
            assert cid not in found_ids, f"Duplicate baseline control ID found: {cid}"
            found_ids.add(cid)
            
            # Check row columns completeness
            cols = [c.strip() for c in row.split("|")[1:-1]]
            assert len(cols) == 12, f"Baseline control {cid} does not have 12 columns, got {len(cols)}"
            # Columns: ID, Name, Domain, Orig Prio, Orig App, Orig Status, Sales AI Prio, Rationale, Mechanism, Owner, TestID, TargetStep
            sales_prio = cols[6]
            assert "**P0**" in sales_prio or "**P1**" in sales_prio or "**P2**" in sales_prio or "**N/A**" in sales_prio

    assert len(found_ids) == 70, f"Expected exactly 70 baseline control IDs, found {len(found_ids)}"
    for i in range(1, 71):
        expected_id = str(i).zfill(2)
        assert expected_id in found_ids, f"Missing baseline control ID: {expected_id}"

def test_sai_extension_controls_traceability():
    content = MAPPING_FILE.read_text(encoding="utf-8")
    
    found_sai = set()
    for row in content.splitlines():
        match = re.match(r"^\|\s*\*\*(SAI-\d{2})\*\*\s*\|", row.strip())
        if match:
            sai_id = match.group(1)
            assert sai_id not in found_sai, f"Duplicate SAI control ID found: {sai_id}"
            found_sai.add(sai_id)
            
            cols = [c.strip() for c in row.split("|")[1:-1]]
            assert len(cols) == 8, f"SAI control {sai_id} does not have 8 columns, got {len(cols)}"

    assert len(found_sai) == 12, f"Expected exactly 12 SAI extension controls, found {len(found_sai)}"
    for i in range(1, 13):
        expected_sai = f"SAI-{str(i).zfill(2)}"
        assert expected_sai in found_sai, f"Missing SAI control ID: {expected_sai}"

def test_priority_reclassifications_for_sales_ai():
    content = MAPPING_FILE.read_text(encoding="utf-8")
    # Verify critical AI controls elevated to P0
    p0_elevations = ["31", "32", "39", "40", "59", "65", "66", "67", "70"]
    for cid in p0_elevations:
        pattern = rf"\|\s*\*\*{cid}\*\*\s*\|.*?\|\s*\*\*P0\*\*\s*\|"
        assert re.search(pattern, content), f"Control {cid} was not elevated to P0 in Sales AI mapping."
    
    # Verify control 18 (NoSQL) is marked N/A with rationale
    pattern_18 = r"\|\s*\*\*18\*\*\s*\|.*?\|\s*\*\*N/A\*\*\s*\|"
    assert re.search(pattern_18, content), "Control 18 (NoSQL) was not properly marked N/A for relational stack."

# 支撑材料与正式复现说明

原始题面和 `C题数据/` 中的工作簿保持不变。论文只维护 LaTeX 与 PDF，不生成 Word。全部命令从工作区根目录执行；下列流程按依赖分批，P2、P3、敏感性、种子和代表窗口均在批内并行。

## 权威数据链

- `processed_data/raw_parquet/`：原始工作簿的字段保真转存。
- `processed_data/unified_holdout/`：统一患者事件、项目任务、训练期医生容量和项目—设备兼容输入。
- `results/p1/`：问题一的需求、预测、峰平、科室、项目时长和医生相对吞吐结果。
- `results/capability/`：项目—设备关系、原50个回退项目、床旁语义和 P2 能力失败分解。
- `results/exact_benchmark/`：P2 代表窗口 CP-SAT 与生产启发式对照。
- `results/p3_exact_benchmark/`：P3 联合场景代表窗口 CP-SAT 与生产启发式对照。
- `results/calibration/`：历史口径到标准化排程的 C0--C7 校准链。
- `results/final_frozen/`：唯一权威 P2、P3、敏感性结果及 `FINAL_RESULT_MANIFEST.json`。
- `figures/paper_final/`：正文使用的矢量图。

旧目录 `results/unified_schedule/` 不属于权威结果；若该目录存在，最终冻结检查会失败。

## 0. 环境和基础输入

```powershell
python -m pip install -r supporting_materials/requirements.txt
python supporting_materials/code/inspect_inputs.py
python supporting_materials/code/extract_to_parquet.py
python supporting_materials/code/audit_data.py
python supporting_materials/code/bundle_sensitivity.py
python supporting_materials/code/analyze_p1.py
python supporting_materials/code/analyze_department_demand.py
python supporting_materials/code/audit_capability.py
python supporting_materials/code/estimate_doctor_project_times.py
python supporting_materials/code/build_unified_inputs.py
python supporting_materials/code/build_legacy_fallback_audit.py
python supporting_materials/code/verify_model_semantics.py
```

以上命令存在文件级依赖，按顺序执行。后续批次使用下列 PowerShell 辅助函数统一接收并检查后台进程：

```powershell
function Complete-CheckedJobs($Jobs) {
    $Jobs | Wait-Job | Out-Null
    $Jobs | Receive-Job
    $failed = @($Jobs | Where-Object State -ne "Completed")
    $Jobs | Remove-Job
    if ($failed.Count -gt 0) { throw "有 $($failed.Count) 个后台任务失败" }
}
$repo = (Get-Location).Path
```

## 1. P2 六策略并行与固定词典序选择

正式入口是六个 `p2-point` 分片；无参数调用或兼容用的 `--stage p2` 不是正式全量入口。

```powershell
$policies = @(
    "FCFS_SHARED", "SLACK_GUARD_SHARED",
    "FCFS_LOAD_BALANCED", "SLACK_LOAD_BALANCED",
    "FCFS_SCARCITY_PRESERVING", "SLACK_SCARCITY_PRESERVING"
)
$jobs = foreach ($policy in $policies) {
    Start-Job -ArgumentList $repo, $policy -ScriptBlock {
        param($repo, $policy)
        Set-Location -LiteralPath $repo
        & python supporting_materials/code/run_pre_freeze_scenarios.py --stage p2-point --policy $policy
        if ($LASTEXITCODE -ne 0) { throw "P2分片失败: $policy" }
    }
}
Complete-CheckedJobs $jobs
python supporting_materials/code/run_pre_freeze_scenarios.py --stage finalize-p2
```

`finalize-p2` 只有在六个分片及其明细均完整时才运行选择，并把选中策略的明细物化到 `results/final_frozen/p2_inpatient_only/`。

## 2. P3 粗网格、局部细化和明细物化

正式粗网格为 0.00 至 0.70、步长 0.05，共15点。每个点独立加载数据、独立写分片。

```powershell
$coarse = 0..14 | ForEach-Object { ($_ * 0.05).ToString("0.00", [Globalization.CultureInfo]::InvariantCulture) }
$jobs = foreach ($alpha in $coarse) {
    Start-Job -ArgumentList $repo, $alpha -ScriptBlock {
        param($repo, $alpha)
        Set-Location -LiteralPath $repo
        & python supporting_materials/code/run_pre_freeze_scenarios.py --stage p3-point --alpha $alpha
        if ($LASTEXITCODE -ne 0) { throw "P3粗网格失败: alpha=$alpha" }
    }
}
Complete-CheckedJobs $jobs
python supporting_materials/code/run_pre_freeze_scenarios.py --stage finalize-p3
```

首次 `finalize-p3` 只产生局部点建议，不能冻结。读取建议并并行补算：

```powershell
$suggestionPath = "supporting_materials/results/final_frozen/p3_joint/local_refinement_suggestion.json"
$local = @((Get-Content -Raw $suggestionPath | ConvertFrom-Json).suggested_alpha_values) | ForEach-Object {
    ([double]$_).ToString("0.####", [Globalization.CultureInfo]::InvariantCulture)
}
if ($local.Count -eq 0) { throw "未生成局部细化点，不能完成正式冻结" }
$jobs = foreach ($alpha in $local) {
    Start-Job -ArgumentList $repo, $alpha -ScriptBlock {
        param($repo, $alpha)
        Set-Location -LiteralPath $repo
        & python supporting_materials/code/run_pre_freeze_scenarios.py --stage p3-point --alpha $alpha
        if ($LASTEXITCODE -ne 0) { throw "P3局部点失败: alpha=$alpha" }
    }
}
Complete-CheckedJobs $jobs
$allAlpha = @($coarse + $local) | Sort-Object -Unique
$grid = $allAlpha -join ","
python supporting_materials/code/run_pre_freeze_scenarios.py --stage finalize-p3 --alpha-grid $grid
```

选中点和 alpha=0 点必须保存明细；二者可以并行。随后再次 finalize，才能把选中分片物化到 `p3_joint/`。

```powershell
$selectionPath = "supporting_materials/results/final_frozen/p3_joint/selection.json"
$selectedAlpha = ([double](Get-Content -Raw $selectionPath | ConvertFrom-Json).selected_alpha).ToString("0.####", [Globalization.CultureInfo]::InvariantCulture)
$detailAlpha = @($selectedAlpha, "0.00") | Sort-Object -Unique
$jobs = foreach ($alpha in $detailAlpha) {
    Start-Job -ArgumentList $repo, $alpha -ScriptBlock {
        param($repo, $alpha)
        Set-Location -LiteralPath $repo
        & python supporting_materials/code/run_pre_freeze_scenarios.py --stage p3-point --alpha $alpha --save-detail
        if ($LASTEXITCODE -ne 0) { throw "P3明细失败: alpha=$alpha" }
    }
}
Complete-CheckedJobs $jobs
python supporting_materials/code/run_pre_freeze_scenarios.py --stage finalize-p3 --alpha-grid $grid
python supporting_materials/code/verify_p2_p3_kernel_equivalence.py
```

## 3. 选中 alpha 下的敏感性和多种子并行

```powershell
$sensitivitySpecs = @(
    [pscustomobject]@{ Label = "preparation_item";  Extra = @() },
    [pscustomobject]@{ Label = "preparation_event"; Extra = @("--preparation-mode", "event") },
    [pscustomobject]@{ Label = "doctor_low";        Extra = @("--capacity-column", "capacity_low") },
    [pscustomobject]@{ Label = "capability_AB";     Extra = @("--capability-mode", "strict") },
    [pscustomobject]@{ Label = "bladder45";         Extra = @("--bladder-minutes", "45") },
    [pscustomobject]@{ Label = "bladder90";         Extra = @("--bladder-minutes", "90") },
    [pscustomobject]@{ Label = "transfer5";         Extra = @("--transfer-minutes", "5") },
    [pscustomobject]@{ Label = "transfer15";        Extra = @("--transfer-minutes", "15") },
    [pscustomobject]@{ Label = "seed_11";           Extra = @("--special-seed", "11") },
    [pscustomobject]@{ Label = "seed_29";           Extra = @("--special-seed", "29") },
    [pscustomobject]@{ Label = "seed_47";           Extra = @("--special-seed", "47") },
    [pscustomobject]@{ Label = "seed_83";           Extra = @("--special-seed", "83") },
    [pscustomobject]@{ Label = "seed_131";          Extra = @("--special-seed", "131") }
)
$jobs = foreach ($spec in $sensitivitySpecs) {
    $extraJson = ConvertTo-Json -Compress -InputObject @($spec.Extra)
    Start-Job -ArgumentList $repo, $selectedAlpha, $spec.Label, $extraJson -ScriptBlock {
        param($repo, $alpha, $label, $extraJson)
        Set-Location -LiteralPath $repo
        $extra = @($extraJson | ConvertFrom-Json)
        & python supporting_materials/code/run_pre_freeze_scenarios.py --stage p3-point --alpha $alpha --label $label @extra
        if ($LASTEXITCODE -ne 0) { throw "敏感性分片失败: $label" }
    }
}
Complete-CheckedJobs $jobs
python supporting_materials/code/finalize_sensitivity_outputs.py
```

该汇总入口只接受上述8个敏感性场景和5个随机种子场景，并在生成论文表图前物化 `sensitivity_metrics.csv`、`special_seed_summary.json` 与 `preparation_granularity_sensitivity.csv`。

## 4. 校准、精确对照、能力分解和独立验证

校准的三个全年变体并行运行，再汇总 C0--C7：

```powershell
$calibrationCases = @("C2_standard_hours", "C3_doctor_capacity", "C4_project_capability")
$jobs = foreach ($case in $calibrationCases) {
    Start-Job -ArgumentList $repo, $case -ScriptBlock {
        param($repo, $case)
        Set-Location -LiteralPath $repo
        & python supporting_materials/code/run_calibration_scenarios.py --scenario $case
        if ($LASTEXITCODE -ne 0) { throw "校准分片失败: $case" }
    }
}
Complete-CheckedJobs $jobs
python supporting_materials/code/run_calibration_scenarios.py --scenario finalize
```

P2/P3 精确代表窗口内部也启用并行；两个基准与两份独立验证互相独立，可同时启动。为避免嵌套过量线程，每个 CP-SAT 子问题固定一个 solver worker。

```powershell
$jobs = @(
    Start-Job -ArgumentList $repo -ScriptBlock {
        param($repo); Set-Location -LiteralPath $repo
        & python supporting_materials/code/benchmark_exact_scheduler.py --parallel-cases 6 --solver-workers 1
        if ($LASTEXITCODE -ne 0) { throw "P2精确基准失败" }
    }
    Start-Job -ArgumentList $repo -ScriptBlock {
        param($repo); Set-Location -LiteralPath $repo
        & python supporting_materials/code/benchmark_exact_p3_scheduler.py --parallel-cases 8 --solver-workers 1
        if ($LASTEXITCODE -ne 0) { throw "P3精确基准失败" }
    }
    Start-Job -ArgumentList $repo -ScriptBlock {
        param($repo); Set-Location -LiteralPath $repo
        & python supporting_materials/code/verify_unified_schedule.py --result-dir supporting_materials/results/final_frozen/p2_inpatient_only
        if ($LASTEXITCODE -ne 0) { throw "P2独立验证失败" }
    }
    Start-Job -ArgumentList $repo -ScriptBlock {
        param($repo); Set-Location -LiteralPath $repo
        & python supporting_materials/code/verify_unified_schedule.py --result-dir supporting_materials/results/final_frozen/p3_joint
        if ($LASTEXITCODE -ne 0) { throw "P3独立验证失败" }
    }
    Start-Job -ArgumentList $repo -ScriptBlock {
        param($repo); Set-Location -LiteralPath $repo
        & python supporting_materials/code/build_capability_failure_audits.py
        if ($LASTEXITCODE -ne 0) { throw "能力失败分解失败" }
    }
)
Complete-CheckedJobs $jobs
```

## 5. 论文同步、技术冻结和最终 QA

先从最终结果重建论文表图和 PDF，再运行论文硬验收以生成论文—结果一致性 JSON。第一次验收时旧 manifest 尚未冻结，最终 QA 可以暂时为 FALSE；但论文硬验收和一致性检查自身必须先通过。随后重建 manifest，再运行一次论文验收，让最终 QA 重新读取当前 manifest 和当前权威结果。

```powershell
python supporting_materials/code/build_unified_paper_tables.py
python supporting_materials/code/make_unified_figures.py
python paper/build_latex.py
python supporting_materials/code/paper_hard_acceptance.py
python supporting_materials/code/finalize_model_audits.py
python supporting_materials/code/paper_hard_acceptance.py
```

最终必须同时满足：

- `SECOND_STAGE_FINAL_TECHNICAL_AUDIT.md` 中 `MODEL_AND_RESULTS_FROZEN = TRUE`；
- `qa/MODEL_RESULT_FINAL_CONSISTENCY_AUDIT.json` 的 `passed` 为 `true`；
- `qa/PAPER_HARD_ACCEPTANCE_REPORT.md` 与 `qa/FINAL_QA_REPORT.md` 均为通过；
- P2/P3 独立验证包含跨全部 event 的同患者互斥和跨室转运检查，而不是旧版仅 event 内检查。

## 解释边界

- 训练期为 2019-03-01 至 2024-03-31，留出期为 2024-04-01 至 2025-03-31。
- 题给区间中点/上界是排程时长；相邻报告间隔只用于比较相对负荷。
- 门诊、体检报告日只构造回顾性计划日压力，不是真实预约日。
- 项目—设备集合只来自题面表1；无法确认的项目保留在完成率分母但不赋予设备。
- 医生容量是训练期星期—5分钟槽总并发代理，不是未来实名资质矩阵。
- 60分钟憋尿和10分钟转运为情景参数，均用敏感性场景检验。
- 最后一个任务结束代理报告提交，48小时率是预约排程层估计。
- P3 的 ε 是全年背景完整完成数下限；逐日 quota 不属于正式模型。

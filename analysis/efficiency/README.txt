TEM-FLOW 1.0.0 computational efficiency reproduction

Purpose
This folder repeats the matched comparison reported in manuscript Table 1
and Supplementary Figure S2. All inputs are synthetic. No chemistry values,
restricted records, network service, or account is needed for the calculation.

What is repeated
The unchanged TEM-FLOW tree kernel, expanded-network Dinic solver and
paired-allocation HiGHS linear program compute the same prospective uncertainty
profiles under the same mass, accounting groups, errors and missing-record
allowances. These are worst-case widths over possible shared readings, not
estimated shipments or conditional intervals for particular observed values.
There are 15 matched cases and six additional TEM-FLOW-only scaling cases.

Preparation
Use Python 3.13. The recorded run used Python 3.13.15, NumPy 2.5.1 and SciPy
1.18.0. Open a terminal in this folder. Install the two numerical libraries:
  python -m pip install -r requirements.txt
The existing TEM-FLOW desktop Python already contains these libraries.
The Windows button below uses that runtime if included with your copy, or
creates a separate environment using an installed Python 3.13.

Repeat the comparison
  python reproduce_benchmark.py --output results-new
On Windows, double-click REPEAT_BENCHMARK.cmd. Leave the window open while the
51 method/case evaluations run. The whole test takes several minutes. The
program prints progress and the path of an ordinary web report to open.
Every repeat must use a new output folder; supplied results are preserved.

Read the results
REPORT.html explains the fresh comparison. VERIFICATION.json checks numerical
agreement with the recorded profiles and reports speed separately. RESULTS.csv
contains medians and ranges. RESULTS.json and RAW_RUNS.jsonl retain complete
profiles, individual timing samples and memory counters. ENVIRONMENT.json
records your Python/library versions. Inputs and the protocol are saved too.
The program exits with an error if results disagree, if an unexpected method
error occurs, or if a previously completed case now times out. Examine the
report before interpreting an incomplete run; a slower computer may need a
separately declared longer time limit, which changes the protocol.

Rebuild the published numerical table without a new timing run
  python reproduce_benchmark.py --check-recorded --output table-from-recorded
This checks file hashes and the input generator, and recreates Table 1 from
recorded/RESULTS.json. It is a check of the supplied evidence, not a new speed
measurement. The recorded data remain the source for the manuscript numbers.
To regenerate Supplementary Figure S2, install Matplotlib and run:
  python plot_benchmark.py --results recorded/RESULTS.json --output figure-new

Expected numerical result and variable timings
The recorded run contains 28 completed comparisons and 1,776 compared values,
all with zero numerical difference. HiGHS timed out in two cases at the stated
10-second limit. Timeouts are not completion times or exact speed ratios.
New elapsed times will differ with hardware and system load. Numerical checks
use an absolute tolerance of 1e-7. Speed agreement is reported separately;
the program does not assume that TEM-FLOW must be faster on every computer.

Limits of the contribution
Both reference implementations enumerate missing-record combinations. The
measured gain includes avoiding that enumeration through the tree recurrence.
The comparison does not establish superiority over all specialized published
algorithms, crossing-group performance, map responsiveness, or a memory gain.
The original full comparator-development record is preserved separately in
the dated efficiency-benchmark archive, without pooling superseded timings.

Reproduction files
code/benchmark.py is the executed comparison with only a fresh-output guard.
code/vendor/temflow/_structural_tree.py is byte-identical to the production
kernel in ../../src/temflow. The runner verifies that identity and hashes of
the code and recorded evidence before timing. Version 1.0.0 is unchanged.

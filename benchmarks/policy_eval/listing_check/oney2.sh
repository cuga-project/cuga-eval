#!/bin/zsh
# arm profile snapshot model trial bind shortlister set tasks...
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
A=$1 P=$2 S=$3 M=$4 T=$5 B=$6 SL=$7 SET=$8; shift 8
[ "$B" != "-" ] && export AB_FC_BIND=$B
[ "$SL" != "-" ] && export AB_SHORTLISTER=$SL
~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench automationbench --profile $P --set $SET --snapshot $S --trial $T --run $A --model $M -j 2 --proxy http://127.0.0.1:8801 ${@:+--tasks} $@ > /tmp/aud/${A}_t$T.out 2>&1

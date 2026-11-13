FILES="sparring/effects/ops_core.py sparring/effects/select.py data/heroes/effects/schema.json tools/validate_effects.py sparring/session_rage.py data/i18n/en.json data/i18n/es.json docs/effects-dsl.md docs/live-checklist.md features.json"
for i in $(seq 1 120); do
  git pull --rebase --autostash -q >/dev/null 2>&1
  n=0; for f in $FILES; do grep -q "^$f " LOCKS && n=1; done
  if [ $n = 0 ]; then
    t=$(date -u +%H:%MZ)
    for f in $FILES; do printf '%s  raptors  finish raptors  %s\n' $f $t >> LOCKS; done
    git add LOCKS; git commit -qm 'lock: raptors finish'
    if git push -q 2>/dev/null; then echo LOCKED $t; exit 0; fi
    git reset -q --hard HEAD~1; git pull --rebase --autostash -q >/dev/null 2>&1
  fi
  sleep 15
done
echo TIMEOUT

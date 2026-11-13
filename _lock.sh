FILES="sparring/effects/state.py tests/test_d1_bot_cards.py sparring/ai_medusa.py data/i18n/en.json data/i18n/es.json features.json docs/live-checklist.md README.md docs/card-identity.md docs/effects-dsl.md"
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

#!/usr/bin/env bash

set -euo pipefail

if [[ ! -f supabase/signing_keys.json ]]; then
    printf '[]\n' > supabase/signing_keys.json
    bunx supabase gen signing-key --append
fi

bunx supabase start

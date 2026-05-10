# ThirdEye — backend + iOS + web dev runner.
#
#   make run        full stack: router + vision + iPhone app + web UI
#                   (iOS reinstalls clean every run → onboarding from scratch)
#   make start      alias for `make run`
#   make backend    just router + vision (no iPhone/web build)
#   make ios        rebuild + wipe + reinstall + launch iOS app on iPhone
#   make ios-uninstall  manually wipe the app sandbox on the connected phone
#   make web        configure + launch the figma-ui operator console (:5173)
#   make web-config regenerate apps/figma-ui/.env.local from PUBLIC_BASE_URL/LAN IP
#   make router     just the FastAPI action router (:8001)
#   make vision     just the vision pipeline (assumes router is up)
#   make camera     verify webcam permission + index 0 opens
#   make health     curl the running router's /health
#   make stop       kill any backend started by `make run`
#
# Override the port: `make run ROUTER_PORT=8090`.

SHELL          := /bin/bash

PYTHON         := .venv/bin/python
ROUTER_PORT    ?= 8001
ROUTER_URL     := http://127.0.0.1:$(ROUTER_PORT)
ROUTER_LOG     := /tmp/thirdeye-router.log
ROUTER_PIDFILE := /tmp/thirdeye-router.pid
IOS_DIR        := apps/ios
IOS_BUNDLE     := com.aditya.thirdeye
IOS_TEAM       := K4JS4H52Y6
IOS_CONFIG     := $(IOS_DIR)/Sources/Generated/BackendConfig.swift
# Pinning DerivedData to a per-repo path stops `ios-install` from picking a
# stale build out of `~/Library/.../DerivedData/ThirdEye-<hash>` whenever
# Xcode's GUI and our CLI build land in different hashes. Every `make run`
# now writes + reads from the same deterministic location.
IOS_DERIVED    := $(IOS_DIR)/.build
IOS_APP        := $(IOS_DERIVED)/Build/Products/Debug-iphoneos/ThirdEye.app
WEB_DIR        := apps/figma-ui
WEB_PORT       ?= 5173
WEB_ENV        := $(WEB_DIR)/.env.local
WEB_LOG        := /tmp/thirdeye-web.log
WEB_PIDFILE    := /tmp/thirdeye-web.pid

.PHONY: help run start backend router vision camera health stop check ios ios-config ios-build ios-uninstall ios-install ios-launch web web-config web-stop

help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

check: ## Verify .venv + .env are in place
	@test -x "$(PYTHON)" || { echo "❌ .venv missing. Run:  python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }
	@test -f .env       || { echo "❌ .env missing. Copy .env.example → .env and fill in keys."; exit 1; }
	@echo "✅ env ok ($$($(PYTHON) --version 2>&1))"

start: run ## Alias for `make run`

# ---- Full-stack runner --------------------------------------------------
# 1. Bring router up, wait for /health.
# 2. (best-effort) build + install + launch the iOS app on a connected iPhone.
# 3. Print READY banner. 4. Run vision in foreground; Ctrl+C kills the whole thing.
run: check camera ## Full stack: router + vision + fresh iPhone install + web
	@$(MAKE) --no-print-directory stop >/dev/null 2>&1 || true
	@bash -c '\
	  set -uo pipefail; \
	  echo "▶ starting action router on :$(ROUTER_PORT)…"; \
	  $(PYTHON) -m scripts.run_service --port $(ROUTER_PORT) >"$(ROUTER_LOG)" 2>&1 & \
	  ROUTER_PID=$$!; \
	  echo $$ROUTER_PID > "$(ROUTER_PIDFILE)"; \
	  trap "echo; echo \"↩ stopping router (pid $$ROUTER_PID)\"; kill $$ROUTER_PID 2>/dev/null || true; rm -f $(ROUTER_PIDFILE); exit 0" EXIT INT TERM; \
	  for i in $$(seq 1 60); do \
	    if curl -fsS "$(ROUTER_URL)/health" >/dev/null 2>&1; then break; fi; \
	    if ! kill -0 $$ROUTER_PID 2>/dev/null; then \
	      echo "❌ router exited before becoming ready. Tail of $(ROUTER_LOG):"; \
	      tail -30 "$(ROUTER_LOG)" || true; \
	      exit 1; \
	    fi; \
	    sleep 0.5; \
	  done; \
	  if ! curl -fsS "$(ROUTER_URL)/health" >/dev/null 2>&1; then \
	    echo "❌ router never came up; tail $(ROUTER_LOG)"; exit 1; \
	  fi; \
	  echo "✅ router ready"; \
	  echo; \
	  echo "▶ refreshing iPhone app (skipped if no device connected)…"; \
	  $(MAKE) --no-print-directory ios || echo "⚠ iPhone build/install skipped or failed — backend keeps running."; \
	  echo; \
	  echo "▶ launching web operator console on :$(WEB_PORT) (background)…"; \
	  $(MAKE) --no-print-directory web-bg || echo "⚠ web launch skipped — backend keeps running."; \
	  echo; \
	  echo "════════════════════════════════════════════════════════"; \
	  echo "  ✅ READY"; \
	  echo "  router : $(ROUTER_URL)  (also at $$(make --no-print-directory _lan_url 2>/dev/null))"; \
	  echo "  web    : http://localhost:$(WEB_PORT) (log $(WEB_LOG))"; \
	  echo "  health : $$(curl -fsS $(ROUTER_URL)/health)"; \
	  echo "  log    : $(ROUTER_LOG)"; \
	  echo "  vision : starting now (Ctrl+C to stop everything)"; \
	  echo "════════════════════════════════════════════════════════"; \
	  echo; \
	  trap "echo; echo \"↩ stopping router (pid $$ROUTER_PID) + web\"; kill $$ROUTER_PID 2>/dev/null || true; rm -f $(ROUTER_PIDFILE); $(MAKE) --no-print-directory web-stop >/dev/null 2>&1 || true; exit 0" EXIT INT TERM; \
	  $(PYTHON) -m scripts.run_vision \
	'

backend: check camera ## Backend only (router + vision), no iPhone build
	@$(MAKE) --no-print-directory stop >/dev/null 2>&1 || true
	@bash -c '\
	  set -uo pipefail; \
	  $(PYTHON) -m scripts.run_service --port $(ROUTER_PORT) >"$(ROUTER_LOG)" 2>&1 & \
	  ROUTER_PID=$$!; echo $$ROUTER_PID > "$(ROUTER_PIDFILE)"; \
	  trap "kill $$ROUTER_PID 2>/dev/null || true; rm -f $(ROUTER_PIDFILE); exit 0" EXIT INT TERM; \
	  for i in $$(seq 1 60); do curl -fsS "$(ROUTER_URL)/health" >/dev/null 2>&1 && break; sleep 0.5; done; \
	  echo "✅ READY · router $(ROUTER_URL) · log $(ROUTER_LOG)"; \
	  $(PYTHON) -m scripts.run_vision \
	'

router: check ## Just the action router (foreground)
	$(PYTHON) -m scripts.run_service --port $(ROUTER_PORT)

vision: check ## Just the vision pipeline (assumes router up)
	$(PYTHON) -m scripts.run_vision

camera: ## Verify built-in MacBook webcam (CAMERA_SOURCE=0) is openable
	@$(PYTHON) -c "import cv2, sys; cap = cv2.VideoCapture(0); ok, _ = (cap.isOpened(), cap.read()); cap.release(); sys.exit(0 if ok else 1)" 2>/dev/null && echo "✅ webcam ok (index 0)" || { \
	  echo ""; \
	  echo "❌ Camera permission denied (or webcam unavailable)."; \
	  echo "   Opening System Settings → Privacy & Security → Camera…"; \
	  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"; \
	  echo "   → Toggle ON for your terminal app, then re-run: make run"; \
	  exit 1; \
	}

health: ## Curl the running router's /health
	@curl -fsS "$(ROUTER_URL)/health" | $(PYTHON) -m json.tool || { echo "router not up at $(ROUTER_URL)"; exit 1; }

stop: ## Kill the router + web started by `make run`
	@if [[ -f "$(ROUTER_PIDFILE)" ]]; then PID=$$(cat "$(ROUTER_PIDFILE)"); if kill -0 $$PID 2>/dev/null; then echo "stopping router pid $$PID"; kill $$PID || true; fi; rm -f "$(ROUTER_PIDFILE)"; fi
	@pkill -f "scripts.run_service" 2>/dev/null || true
	@pkill -f "scripts.run_vision"  2>/dev/null || true
	@$(MAKE) --no-print-directory web-stop >/dev/null 2>&1 || true
	@echo "✅ stopped"

# ---- iOS targets --------------------------------------------------------

# Pick a backend URL the iPhone can dial. ngrok PUBLIC_BASE_URL > LAN IP > localhost.
_resolve_backend_url = $$( \
	if grep -qE '^PUBLIC_BASE_URL=https?://[^[:space:]]+$$' .env 2>/dev/null; then \
	  grep -E '^PUBLIC_BASE_URL=' .env | head -1 | cut -d= -f2-; \
	elif IP=$$(ipconfig getifaddr en0 2>/dev/null) && [[ -n $$IP ]]; then \
	  echo "http://$$IP:$(ROUTER_PORT)"; \
	else \
	  echo "http://127.0.0.1:$(ROUTER_PORT)"; \
	fi)

_lan_url:
	@URL=$(call _resolve_backend_url); echo "$$URL"

ios-config: ## Generate iOS BackendConfig.swift from .env
	@URL=$(call _resolve_backend_url); \
	  echo "// Generated by 'make ios-config'. Do not edit by hand." > $(IOS_CONFIG); \
	  echo "// Source: .env PUBLIC_BASE_URL or Mac LAN IP." >> $(IOS_CONFIG); \
	  echo "" >> $(IOS_CONFIG); \
	  echo "enum BackendConfig {" >> $(IOS_CONFIG); \
	  echo "    static let defaultURL = \"$$URL\"" >> $(IOS_CONFIG); \
	  echo "}" >> $(IOS_CONFIG); \
	  echo "✅ iOS BackendConfig.swift → $$URL"

ios-build: ios-config ## xcodegen + build for connected iPhone (pinned DerivedData)
	@cd $(IOS_DIR) && xcodegen generate >/dev/null
	@DEVICE_ID=$$(xcrun xctrace list devices 2>&1 | grep -E "iPhone" | grep -v "Simulator" | head -1 | sed -E 's/.*\(([A-F0-9-]+)\).*/\1/'); \
	  if [[ -z $$DEVICE_ID ]]; then \
	    echo "❌ no iPhone connected"; exit 1; \
	  fi; \
	  echo "→ building for device $$DEVICE_ID → $(IOS_APP) …"; \
	  cd $(IOS_DIR) && xcodebuild -project ThirdEye.xcodeproj -scheme ThirdEye \
	    -destination "id=$$DEVICE_ID" -configuration Debug \
	    -derivedDataPath ./.build \
	    -allowProvisioningUpdates DEVELOPMENT_TEAM=$(IOS_TEAM) \
	    build 2>&1 | tail -3
	@test -d "$(IOS_APP)" || { echo "❌ build succeeded but $(IOS_APP) not found"; exit 1; }
	@echo "✅ iOS build done · $(IOS_APP) (mtime $$(stat -f %Sm "$(IOS_APP)"))"

_ios_device_id = $$(xcrun devicectl list devices 2>/dev/null | grep -E "iPhone" | grep -E "connected" | grep -v "no DDI" | grep -oE '[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}' | head -1)

# Uninstall before install so every `make run` is a true fresh start —
# wipes UserDefaults (`onboarded`, `pin_hash`, `identity_json`), saved
# face-scan data, and any cached LAN cameras. Skipped silently if the
# app wasn't installed yet (first run on a clean phone).
ios-uninstall: ## Uninstall ThirdEye from the connected iPhone (wipes app sandbox)
	@DEV=$(_ios_device_id); \
	  if [[ -z $$DEV ]]; then echo "⚠ no iPhone connected — skipping uninstall"; exit 0; fi; \
	  echo "→ wiping previous install of $(IOS_BUNDLE) so onboarding restarts from scratch…"; \
	  xcrun devicectl device uninstall app --device $$DEV $(IOS_BUNDLE) 2>&1 | tail -1 || true

ios-install: ## Install the latest iOS Debug build on the connected iPhone
	@APP="$(IOS_APP)"; \
	  if [[ ! -d $$APP ]]; then echo "❌ no built ThirdEye.app at $$APP — run 'make ios-build' first"; exit 1; fi; \
	  DEV=$(_ios_device_id); \
	  if [[ -z $$DEV ]]; then echo "❌ no iPhone connected to devicectl"; exit 1; fi; \
	  echo "→ installing $$APP (built $$(stat -f %Sm "$$APP")) on $$DEV…"; \
	  xcrun devicectl device install app --device $$DEV "$$APP" 2>&1 | tail -3

ios-launch: ## Launch ThirdEye on the connected iPhone (no-op if locked)
	@DEV=$(_ios_device_id); \
	  if [[ -z $$DEV ]]; then echo "⚠ no iPhone connected"; exit 0; fi; \
	  OUT=$$(xcrun devicectl device process launch --device $$DEV $(IOS_BUNDLE) 2>&1); \
	  if echo "$$OUT" | grep -q "Locked"; then \
	    echo "🔒 iPhone is locked — unlock it and tap the ThirdEye icon"; \
	  else \
	    echo "$$OUT" | tail -2; \
	  fi

ios: ios-build ios-uninstall ios-install ios-launch ## Rebuild + wipe + install + launch on iPhone
	@echo "✅ iPhone app refreshed (full onboarding flow on next launch)"

# ---- Web targets --------------------------------------------------------
# The Next.js operator console (apps/web) reads NEXT_PUBLIC_BACKEND_URL
# from .env.local, mirroring the BackendConfig.swift pattern so a fresh
# laptop can boot the brain + the web UI with no manual config.

web-config: ## Generate apps/figma-ui/.env.local from .env (localhost backend + ngrok frames)
	@PUBLIC_BASE=$$(grep -E '^PUBLIC_BASE_URL=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r'); \
	  echo "# Generated by 'make web-config'. Do not edit by hand." > $(WEB_ENV); \
	  echo "# The web app runs on the same Mac as the action router, so it" >> $(WEB_ENV); \
	  echo "# always talks to localhost. PUBLIC_BASE_URL only governs the" >> $(WEB_ENV); \
	  echo "# absolute URL used for media/frame thumbnails (cross-device)." >> $(WEB_ENV); \
	  echo "VITE_BACKEND_URL=http://127.0.0.1:$(ROUTER_PORT)" >> $(WEB_ENV); \
	  if [[ -n "$$PUBLIC_BASE" ]]; then \
	    echo "VITE_PUBLIC_BASE_URL=$$PUBLIC_BASE" >> $(WEB_ENV); \
	  fi; \
	  echo "✅ figma-ui .env.local → backend=http://127.0.0.1:$(ROUTER_PORT) frames=$${PUBLIC_BASE:-http://127.0.0.1:$(ROUTER_PORT)}"

web: web-config ## Launch the figma-ui operator console (foreground, :$(WEB_PORT))
	@if [[ ! -d $(WEB_DIR)/node_modules ]]; then \
	  echo "▶ installing figma-ui deps (first run)…"; \
	  cd $(WEB_DIR) && pnpm install --prefer-offline; \
	fi
	@cd $(WEB_DIR) && npx --yes vite --host 127.0.0.1 --port $(WEB_PORT)

web-bg: web-config ## Launch figma-ui in the background (used by `make run`)
	@if [[ ! -d $(WEB_DIR)/node_modules ]]; then \
	  echo "▶ installing figma-ui deps (first run)…"; \
	  (cd $(WEB_DIR) && pnpm install --prefer-offline) >/dev/null 2>&1 || \
	    { echo "⚠ pnpm install failed — skipping web"; exit 0; }; \
	fi
	@$(MAKE) --no-print-directory web-stop >/dev/null 2>&1 || true
	@cd $(WEB_DIR) && (npx --yes vite --host 127.0.0.1 --port $(WEB_PORT) >$(WEB_LOG) 2>&1 & echo $$! > /tmp/thirdeye-web.pid)
	@for i in $$(seq 1 40); do \
	  if curl -fsS "http://localhost:$(WEB_PORT)" >/dev/null 2>&1; then \
	    echo "✅ figma-ui ready at http://localhost:$(WEB_PORT)"; exit 0; \
	  fi; \
	  sleep 0.5; \
	done; \
	echo "⚠ web not responding yet — check $(WEB_LOG)"

web-stop: ## Kill the background figma-ui dev server started by `make run`
	@if [[ -f "$(WEB_PIDFILE)" ]]; then PID=$$(cat "$(WEB_PIDFILE)"); if kill -0 $$PID 2>/dev/null; then echo "stopping web pid $$PID"; kill $$PID || true; fi; rm -f "$(WEB_PIDFILE)"; fi
	@pkill -f "vite.*--port $(WEB_PORT)" 2>/dev/null || true
	@echo "✅ web stopped"

/* Extracted from voice_copilot.html by scripts/frontend_csp_build.py */
        const feed = document.getElementById("copilotFeed");
        const commandInput = document.getElementById("commandInput");
        const sendBtn = document.getElementById("sendBtn");
        const mfaModal = document.getElementById("mfaModal");
        const mfaInput = document.getElementById("mfaInput");
        const confirmActionBtn = document.getElementById("confirmActionBtn");

        let pendingActionToken = null;

        function runQuery(text) {
            commandInput.value = text;
            sendCommand();
        }

        async function sendCommand() {
            const text = commandInput.value.trim();
            if (!text) return;

            addMsg("manager", text);
            commandInput.value = "";

            try {
                const resp = await SalesApi.fetch("/api/v1/voice/copilot/command", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ command_text: text })
                });

                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    addMsg("copilot", "Commande refusée : " + (data.detail && data.detail.message || data.detail || resp.status));
                    return;
                }
                addMsg("copilot", data.insight_text);

                if (data.requires_confirmation && data.action_preview) {
                    pendingActionToken = data.action_preview.action_token;
                    mfaModal.style.display = "block";
                    addActionCard(data.action_preview);
                } else {
                    mfaModal.style.display = "none";
                    pendingActionToken = null;
                }
            } catch (e) {
                addMsg("copilot", "Erreur lors du traitement de la commande: " + e.message);
            }
        }

        confirmActionBtn.addEventListener("click", async () => {
            if (!pendingActionToken) return;
            const code = mfaInput.value.trim();
            if (!code) {
                addMsg("copilot", "Saisissez votre code MFA à 6 chiffres pour confirmer.");
                return;
            }

            try {
                const resp = await SalesApi.fetch("/api/v1/voice/copilot/confirm-action", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        action_token: pendingActionToken,
                        totp_code: code,
                        confirmed: true
                    })
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    addMsg("copilot", "Confirmation refusée : " + (data.detail && data.detail.message || data.detail || resp.status));
                    return;
                }
                addMsg("copilot", data.message);
                mfaModal.style.display = "none";
                mfaInput.value = "";
                pendingActionToken = null;
            } catch (e) {
                addMsg("copilot", "Erreur de confirmation MFA : " + e.message);
            }
        });

        sendBtn.addEventListener("click", sendCommand);
        commandInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") sendCommand();
        });

        function addMsg(type, text) {
            const div = document.createElement("div");
            div.className = "msg " + type;
            div.textContent = text;
            feed.appendChild(div);
            feed.scrollTop = feed.scrollHeight;
        }

        function addActionCard(preview) {
            const div = document.createElement("div");
            div.className = "action-card";
            div.innerHTML = `
                <div class="action-header">
                    <span>⚠️ Action Sensible Requérant Confirmation</span>
                    <span style="background: #FEE2E2; color: #DC2626; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem;">Niveau: ${SalesViews.esc(preview.risk_level)}</span>
                </div>
                <div style="font-size: 0.8rem; color: #78350F; margin-bottom: 6px;">${SalesViews.esc(preview.summary)}</div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">Jeton d'action: <code>${SalesViews.esc(preview.action_token.slice(0, 8))}...</code></div>
            `;
            feed.appendChild(div);
            feed.scrollTop = feed.scrollHeight;
        }

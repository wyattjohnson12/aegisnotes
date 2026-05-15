import { endpoints } from "/static/js/api.js";

const form = document.getElementById("login-form");
const errorEl = document.getElementById("login-error");

form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    errorEl.hidden = true;
    errorEl.textContent = "";

    const username = form.username.value.trim();
    const password = form.password.value;
    if (!username || !password) {
        errorEl.hidden = false;
        errorEl.textContent = "Please enter both username and password.";
        return;
    }

    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    submit.textContent = "Signing in…";

    try {
        await endpoints.login(username, password);
        window.location.replace("/dashboard");
    } catch (err) {
        errorEl.hidden = false;
        errorEl.textContent = err.status === 401
            ? "Invalid username or password."
            : (err.message || "Could not sign in.");
    } finally {
        submit.disabled = false;
        submit.textContent = "Sign in";
    }
});

// If we're already signed in, skip the form.
endpoints.me().then((res) => {
    if (res?.user) window.location.replace("/dashboard");
}).catch(() => { /* ignore */ });

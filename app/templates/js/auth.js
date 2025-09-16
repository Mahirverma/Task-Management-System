const form = document.getElementById("loginForm");
const errorMsg = document.getElementById("error-msg");

if (form) {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value.trim();

    if (!email || !password) {
      showError("Please fill in all fields.");
      return;
    }

    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        showError(data.detail || "Invalid credentials");
        return;
      }

      // Save token if API returns it
      if (data.access_token) {
        localStorage.setItem("access_token", data.access_token);
      }

      // Redirect after login
      window.location.href = "/dashboard";
    } catch (err) {
      showError("Something went wrong. Please try again.");
    }
  });
}

function showError(message) {
  errorMsg.textContent = message;
  errorMsg.style.display = "block";
}
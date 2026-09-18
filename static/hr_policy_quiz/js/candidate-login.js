const form = document.getElementById("loginForm");
const errorBox = document.getElementById("errorBox");
const submitBtn = document.getElementById("submitBtn");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideError(errorBox);
  submitBtn.disabled = true;
  submitBtn.textContent = "Signing in...";

  try {
    const data = await apiRequest("/api/candidate/login", {
      method: "POST",
      body: {
        email: document.getElementById("email").value.trim(),
        password: document.getElementById("password").value,
      },
    });
    setToken("candidate", data.access_token);
    window.location.href = "/hr-quiz/quiz";
  } catch (err) {
    showError(errorBox, err.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Sign in";
  }
});

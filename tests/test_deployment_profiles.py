"""Проверяем модель, разрешённую Docker Compose, а не текст манифеста."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NPM = ROOT / "docker-compose.npm.yml"
REQUIRED = {
    "KAMERTON_BIND": "192.0.2.10",
    "PUBLIC_ORIGIN": "https://stt.example.org",
    "TRUSTED_PROXY_IP": "192.0.2.20",
}


@pytest.fixture(scope="module")
def compose_env(tmp_path_factory):
    # Ни `.env` checkout, ни настройки Compose пользователя не должны влиять на результат.
    env = {key: val for key, val in os.environ.items() if key.upper() in {
        "APPDATA", "DOCKER_CONFIG", "HOME", "LOCALAPPDATA", "PATH", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES",
        "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
    }}
    try:
        version = subprocess.run(["docker", "compose", "version"], env=env, capture_output=True, timeout=10)
    except FileNotFoundError:
        pytest.skip("Нужен Docker Compose CLI (демон для config не требуется)")
    if version.returncode:
        pytest.skip("Нужен Docker Compose CLI (демон для config не требуется)")
    return env, tmp_path_factory.mktemp("compose-profile")


@pytest.fixture
def config(compose_env):
    env, directory = compose_env
    env_file = directory / "empty.env"
    env_file.touch()

    def run(*args, variables=REQUIRED, manifest=NPM, dotenv=env_file):
        return subprocess.run(
            ["docker", "compose", "--env-file", str(dotenv), "-f", str(manifest), *args],
            env=env | variables, cwd=directory, capture_output=True, encoding="utf-8", timeout=20,
        )

    return run


def model(config, **kwargs):
    result = config("--profile", "setup", "config", "--format", "json", **kwargs)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def mounts(service):
    for volume in service["volumes"]:
        assert volume["type"] == "bind"
        # Compose versions can omit the default false in normalized JSON.
        assert volume.get("bind", {}).get("create_host_path", False) is False
    return {volume["target"]: Path(volume["source"]) for volume in service["volumes"]}


def test_npm_standalone(config):
    runtime = config("config", "--services")
    assert runtime.returncode == 0, runtime.stderr
    assert runtime.stdout.split() == ["kamerton"]

    resolved = model(config, variables=REQUIRED | {
        "ADMIN_USERNAME": "not-forwarded", "ADMIN_PASSWORD": "not-forwarded",
        "ADMIN_PASSWORD_FILE": "/never-mounted", "API_KEY": "not-forwarded",
        "OWNER_ACCESS": "0", "ENGINE_HOST": "0.0.0.0", "HOST_BIND": "0.0.0.0", "HOST_PORT": "80",
    })
    assert resolved["name"] == "kamerton-npm"
    assert set(resolved["services"]) == {"kamerton", "owner-cli"}
    app, cli = (resolved["services"][name] for name in ("kamerton", "owner-cli"))
    assert len(app["ports"]) == 1
    port = app["ports"][0]
    assert (port["host_ip"], str(port["published"]), port["target"], port["protocol"]) == (
        REQUIRED["KAMERTON_BIND"], "8812", 8080, "tcp",
    )
    assert "--no-proxy-headers" in app["command"]
    assert "--no-access-log" in app["command"]
    assert app["healthcheck"]["test"] == ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/health"]
    assert app["environment"]["OWNER_ACCESS"] == "1"
    assert app["environment"]["PUBLIC_ORIGIN"] == REQUIRED["PUBLIC_ORIGIN"]
    assert app["environment"]["TRUSTED_PROXY_IP"] == REQUIRED["TRUSTED_PROXY_IP"]
    assert not set(app["environment"]) & {"API_KEY", "ALLOW_OWNER_LOCAL_ROLLBACK", "ENGINE_HOST"}
    assert not any(name.startswith("ADMIN_") for name in app["environment"])
    assert "env_file" not in app and "env_file" not in cli
    assert app["build"]["target"] == "standard"
    assert Path(app["build"]["context"]) == ROOT
    assert app["image"] == cli["image"] == "kamerton:npm"
    assert app["pull_policy"] == cli["pull_policy"] == "never"
    assert cli["entrypoint"] == ["python", "-m", "console.owner_cli"]
    assert cli["command"] == ["--help"]
    assert cli["profiles"] == ["setup"]
    assert cli["network_mode"] == "none"
    assert cli["restart"] == "no"
    assert cli["healthcheck"]["disable"] is True
    assert cli["environment"] == {"DATA_DIR": "/data"}
    assert not cli.get("ports") and not cli.get("build")
    assert mounts(app) == {"/data": ROOT / "data", "/models": ROOT / "models"}
    assert mounts(cli) == {"/data": ROOT / "data"}


@pytest.mark.parametrize("field", list(REQUIRED))
@pytest.mark.parametrize("empty", [False, True], ids=["unset", "empty"])
def test_npm_rejects_missing_boundary_setting(config, field, empty):
    env = REQUIRED.copy()
    if empty:
        env[field] = ""
    else:
        del env[field]
    result = config("config", "--quiet", variables=env)
    assert result.returncode != 0 and field in result.stderr


def test_npm_gitops_yaml_only(config, tmp_path):
    manifest = tmp_path / "docker-compose.yml"
    manifest.write_bytes(NPM.read_bytes())
    context = "https://github.com/mazixs/kamerton.git#v1.6.0"
    data, models = tmp_path / "previous-data", tmp_path / "previous-models"
    resolved = model(config, manifest=manifest, variables=REQUIRED | {
        "KAMERTON_BUILD_CONTEXT": context,
        "KAMERTON_DATA_DIR": str(data),
        "KAMERTON_MODEL_DIR": str(models),
        "KAMERTON_PORT": "18999",
        "KAMERTON_IMAGE": "kamerton:arcane-example",
        "KAMERTON_BUILD_TARGET": "gigaam-v4",
    })
    app, cli = (resolved["services"][name] for name in ("kamerton", "owner-cli"))
    assert app["build"]["context"] == context
    assert app["build"]["target"] == "gigaam-v4"
    assert app["image"] == cli["image"] == "kamerton:arcane-example"
    assert str(app["ports"][0]["published"]) == "18999"
    assert mounts(app) == {"/data": data, "/models": models}
    assert mounts(cli) == {"/data": data}
    assert set(tmp_path.iterdir()) == {manifest}


def test_npm_env_example(config):
    result = config("config", "--quiet", variables={}, dotenv=ROOT / ".env.npm.example")
    assert result.returncode == 0, result.stderr


def test_systemd_override_replaces_docker_restart_and_log_rotation(config):
    result = config("-f", str(ROOT / "deploy/compose.systemd.yml"), "config", "--format", "json")
    assert result.returncode == 0, result.stderr
    app = json.loads(result.stdout)["services"]["kamerton"]
    assert app["restart"] == "no"
    assert app["logging"] == {"driver": "journald", "options": {"tag": "kamerton"}}
    assert app["ports"][0]["host_ip"] == REQUIRED["KAMERTON_BIND"]


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
async def test_browser_loads_native_stylesheet_with_public_csp(engine, live_client):
    pw = pytest.importorskip("playwright.async_api")
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    policy = re.search(r'Content-Security-Policy "([^"]+)"', caddyfile).group(1)
    login_html = ROOT / "frontend" / "dist" / "login.html"

    async with pw.async_playwright() as driver:
        if engine == "webkit" and not Path(driver.webkit.executable_path).is_file():
            pytest.skip("Для проверки CSP в Safari нужен Playwright WebKit")
        browser = await driver.webkit.launch() if engine == "webkit" else await driver.chromium.launch(channel="chrome")
        try:
            page = await browser.new_page()
            await page.add_init_script("""window.styleViolations = [];
                document.addEventListener('securitypolicyviolation', event => {
                    if (event.effectiveDirective.startsWith('style-src')) {
                        window.styleViolations.push(event.blockedURI);
                    }
                });""")

            async def serve_login(route):
                await route.fulfill(path=login_html, content_type="text/html", headers={
                    "Content-Security-Policy": policy,
                })

            async def serve_console(route):
                response = await route.fetch()
                await route.fulfill(response=response, headers={
                    **response.headers, "content-security-policy": policy,
                })

            origin = str(live_client.base_url).rstrip("/")
            await page.route(f"{origin}/login", serve_login)
            await page.route(f"{origin}/", serve_console)

            for path, visible_control in [("/login", "#login-form"), ("/", "#main")]:
                await page.goto(origin + path)
                await pw.expect(page.locator(visible_control)).to_be_visible()
                sheet = page.locator("link#react-native-stylesheet[rel=stylesheet]")
                href = await sheet.get_attribute("href")
                assert re.fullmatch(r"/static/assets/react-native-web-[\w-]{8}\.css", href or "")
                assert await sheet.evaluate("link => link.sheet.cssRules.length > 4")
                assert await page.evaluate("window.styleViolations") == []

                switch = page.locator('[data-slot="toggle-group"].lang:visible')
                languages = switch.get_by_role("radio")
                await pw.expect(languages).to_have_count(2)
                contrast = await languages.evaluate_all("""items => {
                    function luminance(color) {
                        const [r, g, b] = color.match(/\\d+/g).map(channel => {
                            const value = Number(channel) / 255;
                            return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
                        });
                        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
                    }
                    return items.map(item => {
                        const {color, backgroundColor} = getComputedStyle(item);
                        const [dark, light] = [luminance(color), luminance(backgroundColor)].sort((a, b) => a - b);
                        return (light + 0.05) / (dark + 0.05);
                    });
                }""")
                assert min(contrast) >= 4.5, (path, contrast)
                english = switch.get_by_role("radio", name="EN")
                russian = switch.get_by_role("radio", name="RU")
                await russian.click()
                await pw.expect(russian).to_have_attribute("aria-checked", "true")
                await pw.expect(english).to_have_attribute("aria-checked", "false")
                await english.click()
                await pw.expect(english).to_have_attribute("aria-checked", "true")
        finally:
            await browser.close()

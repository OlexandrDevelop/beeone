"""Where the site under test runs, and how to reach it (test mechanics only, never for test data)."""
import os
import subprocess


def read_env_file(path):
    """KEY=VALUE lines of a dev env file; a missing file is an empty dict."""
    data = {}
    if path and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k] = v
    return data


class Stack:
    """A dev stack: a container with a bench, a site and the port the site is served on.

    All values are resolved by the caller (the application suite owns its environment variable names).
    `url` wins over the container address.
    """

    def __init__(self, container, site, port, admin_password="admin", url=None,
                 bench_dir="/home/frappe/data/frappe-bench"):
        self.container = container
        self.site = site
        self.port = port
        self.admin_password = admin_password
        self.bench_dir = bench_dir
        self._url = url

    def container_ip(self):
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", self.container],
            capture_output=True, text=True,
        )
        return out.stdout.strip()

    def base_url(self):
        if self._url:
            return self._url.rstrip("/")
        return f"http://{self.container_ip()}:{self.port}"

    def bench(self, *args, site=None, check=True, timeout=1800):
        """Run a bench command for a site in the stack container."""
        cmd = ["docker", "exec", self.container, "bash", "-lc",
               f"cd {self.bench_dir} && bench --site {site or self.site} " + " ".join(args)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if check and res.returncode != 0:
            raise AssertionError(f"bench {' '.join(args)} failed: {res.stdout[-2000:]} {res.stderr[-2000:]}")
        return res

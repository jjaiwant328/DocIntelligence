"""Pure static-page routing logic for the SPA catch-all. No FastAPI/PIL imports,
so it is unit-testable in isolation."""
import os


def resolve_page_file(target_dir: str, full_path: str) -> str:
    """Pick which exported HTML file serves a given route.

    Generic: any exported Next.js page directory (`<page>/index.html`) is
    reachable — no hardcoded route list, so newly added pages (playground,
    builder, workflow, …) work without editing anything. Falls back to the
    landing index.html for unknown routes.
    """
    if full_path.endswith('.html'):
        fp = os.path.join(target_dir, full_path)
        if os.path.exists(fp):
            return fp

    segment = full_path.strip('/').split('/')[0] if full_path else ''
    if segment:
        fp = os.path.join(target_dir, segment, 'index.html')
        if os.path.exists(fp):
            return fp

    return os.path.join(target_dir, 'index.html')

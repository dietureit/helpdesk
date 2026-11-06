"""Seed the AI Analysis issue-code registry (HD AI Issue Code).

Only missing codes are inserted and an edited code is never overwritten, so this is safe to re-run with
`bench execute helpdesk.patches.seed_ai_issue_codes.execute`. Fresh installs skip patches and get the same
seed from `helpdesk.setup.install.after_install`.
"""


def execute():
    from helpdesk.ai_analysis.registry import seed

    seed()

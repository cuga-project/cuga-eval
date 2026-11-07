"""HOOKS_MODULE factory for the HANDBOOK runner: the requirements tracker (policy = what the agent reads, e.g. the SOP)."""


def make_hooks(ctx):
    from cuga.policy_layer.tracker import tracker_from_env

    return tracker_from_env(policy="")

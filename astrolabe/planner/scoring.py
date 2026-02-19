from astrolabe.errors import NotImplementedFeature


def score_targets(*args, **kwargs):
    raise NotImplementedFeature("Planner scoring not implemented")

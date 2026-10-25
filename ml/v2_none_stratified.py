"""동일한 NONE 종류별 할당량에서 세션·클립 배분만 바꾼다.

원래 선택기로 종류별 개수를 계산하고 양성은 전부 유지한다. 각 종류 안에서
세션, 세션 안에서 클립을 고정 seed로 섞어 라운드로빈한다. 클립 안의 창도
균등하게 섞고, 용량이 소진된 세션/클립의 몫은 남은 곳으로 재분배한다.
클립 안의 창 우선순위는 기존 선택기의 섞기/꺼내기 순서를 그대로 유지한다.
시간 구간·라벨·종류 비중·학습 seed는 바꾸지 않는다.
"""
from collections import Counter, defaultdict, deque
from pathlib import PurePosixPath

import numpy as np

import v2

STRATEGY = "session_clip_balanced_v1"


def session_of(source_path):
    path = PurePosixPath(source_path.replace("\\", "/"))
    if path.parent == PurePosixPath("."):
        raise ValueError(f"세션 폴더가 없는 원본 경로: {source_path}")
    return path.parent.as_posix()


def _clip_queue(files, rng):
    order = [sorted(files)[i] for i in rng.permutation(len(files))]
    queues = {}
    for name in sorted(files):
        queues[name] = deque(reversed(files[name]))
    while order:
        active = []
        for name in order:
            if queues[name]:
                yield queues[name].popleft()
                active.append(name)
        order = active


def choose_training(y, meta, seed=v2.SEED):
    if len(y) != len(meta):
        raise ValueError("라벨과 창 메타데이터 길이가 다르다")
    old = v2.choose_training(y, meta, seed)
    quotas = Counter(meta[i]["none_group"] for i in old if y[i] == 0)
    flat = defaultdict(lambda: defaultdict(list))
    for i in np.flatnonzero(y == 0):
        m = meta[i]
        session_of(m["source_path"])
        flat[m["none_group"]][m["source_path"]].append(int(i))
    window_rng = np.random.default_rng(seed)
    groups = defaultdict(lambda: defaultdict(dict))
    # 기존 함수는 삽입 순서대로 파일 창을 shuffle한 뒤 pop()한다.
    # 이 우선순위는 유지하고, 어떤 세션/클립에 몇 개 줄지만 별도 RNG로 바꾼다.
    for kind, files in flat.items():
        for name, indices in files.items():
            window_rng.shuffle(indices)
            groups[kind][session_of(name)][name] = indices
    rng = np.random.default_rng(seed)
    selected = np.flatnonzero(y != 0).tolist()
    for kind in sorted(quotas):
        sessions = groups[kind]
        names = sorted(sessions)
        order = [names[i] for i in rng.permutation(len(names))]
        queues = {name: _clip_queue(sessions[name], rng) for name in names}
        remaining = quotas[kind]
        while remaining and order:
            active = []
            for name in order:
                value = next(queues[name], None)
                if value is not None:
                    selected.append(value)
                    remaining -= 1
                    active.append(name)
                if not remaining:
                    break
            order = active
        if remaining:
            raise ValueError(f"{kind}: 종류별 NONE 할당량을 채우지 못했다")
    result = np.asarray(sorted(selected), dtype=np.int64)
    assert len(result) == len(old) and len(set(result)) == len(result)
    return result

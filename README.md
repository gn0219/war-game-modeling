# War Game Simulation

## 개요
이 프로젝트는 전쟁 게임 시뮬레이션을 구현한 Python 기반 애플리케이션입니다. `database/background.png` 이미지를 기반으로 유닛의 위치, 이동, 전투를 시뮬레이션하고 시각화합니다.

## 주요 기능
- 유닛 위치 및 이동 시뮬레이션
- 전투 시스템 구현
- 시각화 및 애니메이션 생성
- 전투 로그 저장

## Version Information
NOTE: 브랜치 명 바꿈. 아래 설명 참고
- [Initial branch](https://github.com/gn0219/war-game-modeling/tree/initial)
    - 2025-05-13: Merged pull request from @sheom1991
        - Updated map data, set inital position, and established coordinate system and command structure
    - 2025-05-12: Initial project setup by @gn0219

- [Main branch](https://github.com/gn0219/war-game-modeling)
    - 2025-05-20: Bug fixes by @gn0219
    - 2025-05-19: Merged from @mintyoon826's [repository](https://github.com/mintyoon826/war-game-modeling)
        - Implemented mobility (기동) and firepower (화력) logic

## 2025-05-20 규나 변경사항
- 화력 변수명 통일 (모두 영어로 통일)
- 기타 오류 수정
    - CombatUnit Hashable Type으로 변경
    - 단위 시간당 하나의 actor가 여러 target 공격 가능하였던 것을, 하나의 time에 대해 하나의 actor가 하나의 target만 공격 가능하도록 수정
    - 유닛이 죽지 않는 오류 수정
- 로거 분리
    - events와 state_snapshots 따로 저장
- 기타
    - 시뮬레이션 시간이 오래걸려서 원본 config.yaml은 config copy.yaml에 저장하고, 잠시 유닛 개수를 모두 2개로 줄여서 실행해보는중임 (나중에 버그 모두 해결되면 유닛 개수 다시 수정할 예정)

## TODO (2025-05-20 수정)
- 오류 수정 필요
    - 드론이 거의 순간이동함..
    - 움직이지 않는 유닛이 있음
    - 유닛이 죽지 않음
- 드론 구현 필요
- 지금 Eligible_target_list 사용하지 않고 있음 --> 나중에 구현해보고 필요없으면 삭제해도 될 듯
- 지형 특성 반영 구조 추가
    - 가시선 분석 (현재 x, y 좌표만 사용) - `combat.py`, `def los` function 내 조정 필요
    - 수로 등 장애물 인식
- 시각화 수정: 자잘자잘한 오류가 많아서 시각화까지 수정할 수 있을지는 모르겠음


## 프로젝트 구조
```
war-game-modeling/
├── test_simulation.py                # 시뮬레이션 테스트 및 실행
├── config.yaml                       # 시뮬레이션 설정 파일
├── requirements.txt                  # 의존성 패키지 목록
├── README.md                         # 프로젝트 문서
├── models/                           # 핵심 모델 구현
│   ├── combat.py                     # 전투 시스템
│   ├── command.py                    # 명령 시스템
│   ├── events.py                     # 이벤트 관리
│   ├── logging.py                    # 로깅 시스템
│   ├── probabilities.py              # 확률 계산
│   ├── terrain.py                    # 지형 시스템
│   ├── unit.py                       # 유닛 정의
│   └── visualization.py              # 시각화 시스템
├── database/                         # 데이터 파일
    ├── background.png                # 배경 이미지
│   ├── rifle_hit_prob.csv            # 소총 명중 확률
│   ├── rifle_damage_prob.csv         # 소총 피해 확률
│   ├── tank_hit_prob.csv             # 전차 명중 확률
│   └── tank_damage_prob.csv          # 전차 피해 확률
└── results/                          # 시뮬레이션 결과
    ├── simulation_log_events.json    # 시뮬레이션 로그
    ├── simulation_log_snapshots.json # 시뮬레이션 로그
    ├── simulation_metrics.png        # 시뮬레이션 결과 그래프
    ├── final_state.png               # 종료 시점 이미지
    └── simulation.mp4                # 시뮬레이션 동영상
```

## 시뮬레이션 프로세스
1. **초기화**: config.yaml 파일에서 설정을 로드하고 유닛을 초기화합니다.
2. **시뮬레이션 루프**: 각 시간 단계마다 다음을 수행합니다.
   - 유닛 상태 업데이트
   - 전투 처리
   - 이동 처리
   - 이벤트 로깅
   - 상태 스냅샷 저장
3. **시각화 및 로그 저장**: 시뮬레이션 결과를 시각화하고 로그를 저장합니다.
   - MP4 애니메이션 생성 `simulation.mp4`
   - Final State 이미지 저장 `final_state.png`
   - 결과 그래프 생성 `simulation_metrics.png`
   - 요약 로그 (공격 정보) 저장 `log.txt`
   - 전체 로그 저장 `simulation_log.json`

## 좌표계
- (0,0): background.png의 좌상단(왼쪽 위) 픽셀
- (width-1, height-1): 우하단(오른쪽 아래) 픽셀
    - (996, 693)
- 모든 유닛 위치/이동/거리 계산은 이 픽셀 좌표계만 사용

## 실행 방법
1. 패키지 설치:
   ```bash
   pip install -r requirements.txt
   ```

2. config.yaml에서 유닛 위치 등 설정

3. 시뮬레이션 실행:
   ```bash
   python test_simulation.py
   ```

4. 결과 확인:
   - results/ 폴더에서 시뮬레이션 결과 확인
   - MP4 애니메이션 확인
   - simulation_log.json에서 상세 로그 확인

## 주요 모듈 설명

### models/combat.py
전투 시스템을 구현합니다. 유닛 간 전투, 명중 확률 계산, 피해 처리 등을 담당합니다.

### models/command.py
명령 시스템을 구현합니다. 전투 단계(FIRE_SUPPRESSION, ARMOR_ENGAGEMENT, CLOSE_COMBAT)를 관리합니다.

### models/events.py
이벤트 큐를 관리합니다. 시뮬레이션 중 발생하는 이벤트를 시간순으로 처리합니다.

### models/logging.py
로깅 시스템을 구현합니다. 이벤트와 상태 스냅샷을 기록하고 저장합니다.

### models/probabilities.py
확률 계산 시스템을 구현합니다. 명중 확률, 피해 확률 등을 계산합니다.

### models/terrain.py
지형 시스템을 구현합니다. 지형 효과, 시야 확인 등을 처리합니다.

### models/unit.py
유닛 정의를 포함합니다. 유닛 타입, 상태, 행동 등을 정의합니다.

### models/visualization.py
시각화 시스템을 구현합니다. 맵 시각화, 애니메이션 생성 등을 담당합니다.

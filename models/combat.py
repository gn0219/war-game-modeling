from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple, Set, Optional
import numpy as np
from .unit import Unit, UnitType, UnitState
from .probabilities import ProbabilitySystem, TargetState, DamageType, TankDamageType
from .events import SimulationEvent, EventQueue
from .terrain import TerrainSystem, TerrainEffects
from .command import CommandSystem
import math

class UnitState(Enum):
    ALIVE = "Alive"
    M_KILL = "M-kill"  # Mobility kill
    F_KILL = "F-kill"  # Firepower kill
    MF_KILL  = "MF-kill"   # Mobility+Firepower kill
    K_KILL = "K-kill"  # Complete kill

class Action(Enum):
    MANEUVER = "Maneuver"
    FIRE = "Fire"
    STOP = "Stop"

# 탐지 DB Table (유닛 타입별)
DETECT_DB = {
    UnitType.INFANTRY:    {"detect_range": 1000, "detectability": 0.8,   "mountain_prob": 0.2},
    UnitType.ANTI_TANK:   {"detect_range": 1000, "detectability": 0.8,   "mountain_prob": 0.2},
    UnitType.TANK:        {"detect_range": 3000, "detectability": 2.0,   "mountain_prob": 0.5},
    UnitType.ARTILLERY:   {"detect_range": 2000, "detectability": 1.5,   "mountain_prob": 0.5},
    UnitType.COMMAND_POST:{"detect_range": 1500, "detectability": 1.0,   "mountain_prob": 0.2},
    UnitType.DRONE:       {"detect_range": 5000, "detectability": 0.0001,"mountain_prob": 0.3},
}

# 기동 DB Table (유닛 타입별) -> m/s. 픽셀로 스케일링.
MOVEMENT_SPEED = {
    UnitType.INFANTRY:     1.39,
    UnitType.ANTI_TANK:    1.39,
    UnitType.TANK:         6.95,
    UnitType.ARTILLERY:    1.39,
    UnitType.DRONE:        13.9,
    UnitType.COMMAND_POST: 0,
}

@dataclass
class CombatUnit:
    unit: Unit
    state: UnitState = UnitState.ALIVE
    action: Action = Action.STOP
    target_list: Optional[Set[Unit]] = None
    eligible_target_list: Optional[Set[Unit]] = None
    is_moving: bool = False
    is_defilade: bool = False
    current_goal: Optional[Tuple[float, float]] = None  # 현재 목표 위치 추가
    # 탐지 관련 필드
    detect_range: float = 1000
    detectability: float = 1.0
    mountain_detect_prob: float = 0.2
    failed_detect_count: int = 0

    def __post_init__(self):
        if self.target_list is None:
            self.target_list = set()
        if self.eligible_target_list is None:
            self.eligible_target_list = set()
        # 유닛 타입에 따라 탐지 DB 값 자동 할당
        db = DETECT_DB.get(self.unit.unit_type)
        if db:
            self.detect_range = db["detect_range"]
            self.detectability = db["detectability"]
            self.mountain_detect_prob = db["mountain_prob"]

    def __hash__(self):
        return hash((self.unit, self.state, self.action))

    def __eq__(self, other):
        if not isinstance(other, CombatUnit):
            return NotImplemented
        return (self.unit, self.state, self.action) == (other.unit, other.state, other.action)

    def get_target_state(self) -> TargetState:
        """Get the current target state based on movement and defilade status"""
        if self.is_defilade:
            return TargetState.DS if not self.is_moving else TargetState.DM
        return TargetState.ES if not self.is_moving else TargetState.EM

class CombatSystem:
    """
    전투 시스템의 핵심 로직을 담당하는 클래스.
    - 유닛 탐지, 사격, 피해 처리, 명중 확률 계산 등 전투 관련 기능 제공
    """
    # 무기별 사거리(픽셀 단위, 실제 시뮬레이션에 맞게 조정)
    WEAPON_RANGES = {
        UnitType.INFANTRY: 500,
        UnitType.TANK: 2000,
        UnitType.ANTI_TANK: 1500,
        UnitType.ARTILLERY: 5000,
        UnitType.DRONE: 1000,
        UnitType.COMMAND_POST: 100
    }
    # 무기별 데미지 값
    DAMAGE_VALUES = {
        'rifle': {
            DamageType.MINOR: 10,
            DamageType.SERIOUS: 30,
            DamageType.CRITICAL: 60,
            DamageType.FATAL: 100
        },
        'tank': {
            TankDamageType.MOBILITY: 30,
            TankDamageType.FIREPOWER: 50,
            TankDamageType.TURRET: 70,
            TankDamageType.COMPLETE: 100
        }
    }
    # 곡사 포탄의 치사 반경 (m)
    ARTILLERY_LETHAL_RADIUS = 35.0

    def __init__(self, command_system: CommandSystem, probability_system: Optional[ProbabilitySystem] = None):
        self.prob_system = probability_system or ProbabilitySystem()
        # scale 환산 부분. 픽셀 관련 rescale 되어야 함.
        self.distance_rescale = 1.0
        # 3) 지휘 시스템 참조 (fire_priority 사용용)
        self.command_system = command_system
        # 4) 전체 유닛 목록 (우군피해함수용) → run_simulation 에서 할당 필요
        self._all_units = []

    def set_distance_rescale(self, scale: float):
        """거리 환산 계수 설정 (시뮬레이션 해상도에 맞게)"""
        self.distance_rescale = scale

    def los(self, pos1: Tuple[float, float], pos2: Tuple[float, float], terrain=None) -> bool:
        """Line of Sight(시야) 분석 (지형 반영 가능)

        observer와 상대 사이 거리를 10으로 나눠 각 지점에서 높이 z가
                해당 지점에서의 terrain_height z보다 높으면 탐지 가능
        
        """
        # terrain.check_line_of_sight() 활용 (없으면 True)
        if terrain is not None:
            x1, y1 = int(pos1[0]), int(pos1[1])
            x2, y2 = int(pos2[0]), int(pos2[1])
            return terrain.check_line_of_sight((x1, y1), (x2, y2))
        return True

    def detect(self, observer: CombatUnit, all_units: List[CombatUnit], terrain, z_threshold=None):
        """DB Table/산악지형/누적 탐지 실패 반영 탐지 로직
        observer의 Detect_range * 상대의 Detectability
        """
        observer.target_list.clear()
        if z_threshold is None:
            z_threshold = getattr(terrain, 'mountain_threshold', 50.0)
        for target in all_units:
            if target is observer:
                continue
            # 1. 거리 계산
            distance = self._calculate_distance(observer.unit.position, target.unit.position)
            # 2. 탐지 거리 계산
            detect = observer.detect_range * target.detectability
            if distance > detect:
                continue
            # 3. LOS 체크
            if not self.los(observer.unit.position, target.unit.position, terrain):
                continue
            # 4. 산악지형 확률적 탐지
            x, y = int(target.unit.position[0]), int(target.unit.position[1])
            elevation = terrain.get_elevation(x, y)
            if elevation > z_threshold:
                # 누적 실패 보정
                prob = target.mountain_detect_prob + 0.1 * target.failed_detect_count
                if np.random.random() > prob:
                    target.failed_detect_count += 1
                    continue
                else:
                    target.failed_detect_count = 0
            # 상대 유닛 상태. 화력까지 포함된 후에 보완. 완전 파괴되면 target list에서 아예 제외하고 시작 등
            # 5. 상대팀이면 target_list에 추가
            if observer.unit.team != target.unit.team:
                observer.target_list.add(target)

# 화력
    def _is_valid_target(self, attacker: Unit, target: Unit) -> bool:
        """공격자의 무기 특성에 따라 유효 타겟인지 판정 -> 무기 특성 필터링"""
        # Infantry(Rifle) → Tank, Artillery 사격 불가
        if attacker.unit_type == UnitType.INFANTRY:
            return target.unit.unit_type not in [UnitType.TANK, UnitType.ARTILLERY]

        # Drone 은 사격 불가
        if attacker.unit_type == UnitType.DRONE:
            return False

        # 그 외(탱크, 곡사화기, Command Post 등)는 모두 사격 가능
        return True

    def available_target(self, unit: CombatUnit):
        """무기 특성에 따라 공격 가능한 적 유닛 선별"""
        # detect()로 채워진 unit.target_list 중에서, 무기 특성에 맞는 유효 타겟만 필터링
        # 무기별 사거리 필터링 + 무기 특성 필터링
        unit.eligible_target_list.clear()
        for target in unit.target_list:
            # 무기별 사거리 필터링
            distance = self._calculate_distance(unit.unit.position, target.unit.position)
            max_range = self.WEAPON_RANGES[unit.unit.unit_type]
            if distance > max_range:
                continue
            # 무기 특성 필터링
            if not self._is_valid_target(unit.unit, target):
                continue
            unit.eligible_target_list.add(target)


    def finding_target(self, unit: CombatUnit, event_queue: EventQueue, current_time: float):
        """공격 가능한 타겟 선정 및 사격 이벤트 예약"""
        if unit.state in [UnitState.ALIVE, UnitState.M_KILL] and unit.action == Action.STOP:
            if unit.eligible_target_list:
                unit.action = Action.FIRE
                # 가장 적합한 단일 타겟 선택
                target = self._select_target(unit)
                if target:
                    # 단일 타겟에 대한 사격 이벤트 생성
                    self._schedule_fire(unit, target, event_queue, current_time)

    def _select_target(self, unit: CombatUnit) -> Optional[CombatUnit]:
        """유닛 타입/우선순위에 따라 단일 타겟 선정"""
        if not unit.eligible_target_list:
            return None
        if unit.unit.unit_type == UnitType.ARTILLERY:
            return self._select_artillery_target(unit)
        else:
            return self._select_direct_fire_target(unit)

    def _select_artillery_target(self, unit: CombatUnit) -> CombatUnit:
        """곡사화기(포병)용 타겟 선정 (우선순위/아군 피해 고려)"""
        # 체력이 0보다 큰 유닛만 필터링
        candidates = [t for t in unit.eligible_target_list if t.unit.health > 0]
        if not candidates:
            return None
        
        # 우군 피해 위험도 계산
        friendly_fire_scores = {
            tgt: self.estimate_friendly_fire(
                impact_point=tgt.unit.position, 
                all_units=self._all_units, 
                firing_team=unit.unit.team
            )
            for tgt in candidates
        }

        # 지휘 시스템의 fire_priority 순위 맵핑
        type_priority = {
            UnitType.ARTILLERY: self.command_system.red_command.fire_priority[0],
            UnitType.COMMAND_POST: self.command_system.red_command.fire_priority[1],
            UnitType.TANK: self.command_system.red_command.fire_priority[2],
            UnitType.ANTI_TANK: self.command_system.red_command.fire_priority[3],
            UnitType.INFANTRY: self.command_system.red_command.fire_priority[4],
        }

        # 최종 스코어 계산: 0.8 * (화력 우선순위) - 0.2 * (우군 피해 위험)
        scores = {}
        for tgt in candidates:
            priority_score = type_priority.get(tgt.unit.unit_type, max(type_priority.values()) + 1)
            ff_score = friendly_fire_scores[tgt]
            scores[tgt] = 0.8 * priority_score - 0.2 * ff_score

        # 가장 높은 우선순위(낮은 스코어)의 단일 타겟 반환
        return min(scores, key=scores.get)

    def _select_direct_fire_target(self, unit: CombatUnit) -> CombatUnit:
        """직사화기(직접 조준) 무기용 타겟 선정 (가장 가까운 단일 적)"""
        # 체력이 0보다 큰 유닛만 필터링
        valid_targets = {t for t in unit.eligible_target_list if t.unit.health > 0}
        if not valid_targets:
            return None
        return min(valid_targets, key=lambda t: self._calculate_distance(unit.unit.position, t.unit.position))

    def _schedule_fire(self, unit: CombatUnit, target: CombatUnit, event_queue: EventQueue, current_time: float):
        """FEL(이벤트 큐)에 단일 타겟 사격 이벤트 예약"""
        evt = SimulationEvent(
            time=current_time,
            actor=unit,
            action="Fire",
            details={"targets": [target]}  # 단일 타겟만 포함
        )
        event_queue.schedule(evt)

    def fire(self, unit: CombatUnit, target: CombatUnit, event_queue: EventQueue, current_time: float):
        """단일 타겟에 대한 사격 이벤트 실행"""
        print(f"\nFire event triggered: {unit.unit.id} -> {target.unit.id}")
        if target not in unit.eligible_target_list:
            print(f"Target {target.unit.id} not in eligible targets for {unit.unit.id}")
            return
        if unit.unit.unit_type == UnitType.ARTILLERY:
            print(f"Artillery fire from {unit.unit.id}")
            self._artillery_fire(unit, target, event_queue, current_time)
        else:
            print(f"Direct fire from {unit.unit.id}")
            self._direct_fire(unit, target, event_queue, current_time)
        unit.action = Action.STOP


    def _artillery_fire(self, unit: CombatUnit, target: CombatUnit, event_queue: EventQueue, current_time: float):
        """곡사화기 사격"""
        # [1] 최대 사거리 4700m 체크
        d_pix = self._calculate_distance(unit.unit.position, target.unit.position)
        d = d_pix * self.distance_rescale
        if d > 4700.0:
            return
        # [2] 산탄 오차 σ 계산
        sigma_range   = 0.02 * d
        sigma_deflect = 0.01 * d
        # [3] 오차 샘플링
        dx = np.random.normal(0, sigma_range)
        dy = np.random.normal(0, sigma_deflect)
        # [4] 탄착 지점 계산
        x_aim, y_aim = target.unit.position
        impact_x = x_aim + dx
        impact_y = y_aim + dy
        # [5] 탄착–표적 간 거리 r 계산
        r_pix = self._calculate_distance((impact_x, impact_y), (x_aim, y_aim))
        r = r_pix * self.distance_rescale
        # [6] 치사 반경
        R_L = self.ARTILLERY_LETHAL_RADIUS
        # [7] 피해 확률 D(r)
        p_damage = math.exp(- (r ** 2) / (2 * (R_L ** 2)))
        # [8] 명중 판단
        if np.random.random() > p_damage:
            reload_delay = max(0.0, np.random.normal(loc=4.0, scale=1.0))
            reload_evt = SimulationEvent(
                time=current_time + reload_delay,
                actor=unit,
                action=Action.FIRE.value,      # 재사격도 Fire로 예약
                details={"targets": [target]}
            )
            event_queue.schedule(reload_evt)
            return
        # [9] 피해 타입 결정
        dmg_type = self.prob_system.determine_tank_damage(
            target.get_target_state()
        )
        self._process_tank_damage(unit, target)

        # [10] 무력화 판단
        '''무력화 된 후에 다른 target 경우 - 다시 Main loop 로직 돌기
        무력화 안 된 경우만 재장전 후 바로 재사격'''
        incapacitated = (dmg_type in (TankDamageType.TURRET, TankDamageType.COMPLETE))
        if incapacitated:
            others = [t for t in unit.eligible_target_list if t is not target]
            if not others: # 후보가 없는 경우
                unit.action = Action.STOP
                return
            # 잠시 eligible_target_list를 others로 덮어쓰고
            # _select_artillery_target 로 스코어 기반 다음 목표 선택
            original = unit.eligible_target_list
            try:
                unit.eligible_target_list = set(others)
                next_target = self._select_artillery_target(unit)
            finally:
                # 원래 리스트로 복원 !
                unit.eligible_target_list = original
        else:
            next_target = target

        # [11] 재장전
        reload_delay = max(0.0, np.random.normal(loc=4.0, scale=1.0))
        # 재장전이 끝나는 시점에 unit.action을 STOP으로 바꿈
        reload_evt = SimulationEvent(
            time=current_time + reload_delay,
            actor=unit,
            action=Action.FIRE.value,
            details={"targets": [next_target]}
        )
        event_queue.schedule(reload_evt)


    def _direct_fire(self, unit: CombatUnit, target: CombatUnit, event_queue: EventQueue, current_time: float):
        """직사화기 사격 처리"""
        print(f"Direct fire processing: {unit.unit.id} -> {target.unit.id}")
        distance = self._calculate_distance(unit.unit.position, target.unit.position)
        weapon_type = "tank" if unit.unit.unit_type == UnitType.TANK else "rifle"
        print(f"Weapon type: {weapon_type}, Distance: {distance}")
        
        # [1] 명중 확률
        hit_prob = self.prob_system.get_hit_probability(
            weapon_type,
            distance,
            target.get_target_state()
        )
        print(f"Hit probability: {hit_prob}")
        
        # [2] 명중 여부, 빗나감 -> 재장전만 예약
        if np.random.random() > hit_prob:
            print(f"Miss! Scheduling reload for {unit.unit.id}")
            reload_delay = self._get_reload_delay(unit.unit.unit_type)
            reload_evt = SimulationEvent(
                time=current_time + reload_delay,
                actor=unit,
                action=Action.FIRE.value,
                details={"targets": [target]}
            )
            event_queue.schedule(reload_evt)
            return

        print(f"Hit! Processing damage for {target.unit.id}")
        # [3]~[5] 난수로 피해 판정 수행
        if weapon_type == "rifle":
            dmg_type = self.prob_system.determine_rifle_damage(distance, target.get_target_state())
            print(f"Rifle damage type: {dmg_type}")
            self._process_rifle_damage(unit, target, distance)
            incapacitated = (dmg_type in (DamageType.CRITICAL, DamageType.FATAL))
        else:
            dmg_type = self.prob_system.determine_tank_damage(target.get_target_state())
            print(f"Tank damage type: {dmg_type}")
            self._process_tank_damage(unit, target)
            incapacitated = (dmg_type in (TankDamageType.TURRET, TankDamageType.COMPLETE))
        
        print(f"Target {target.unit.id} incapacitated: {incapacitated}")
        # [6] 무력화 판단
        '''무력화 된 후에 다른 target 경우 - 다시 Main loop 로직 돌기
        무력화 안 된 경우만 재장전 후 바로 재사격'''
        remaining = [t for t in unit.eligible_target_list if t is not target]
        if incapacitated and remaining:
            # 남은 후보 중 가장 가까운 적
            next_tgt = min(
                remaining,
                key=lambda t: self._calculate_distance(unit.unit.position, t.unit.position)
            )
            reload_target = next_tgt
        elif not incapacitated:
            reload_target = target
        else:
            unit.action = Action.STOP # 무력화 성공했으나 대체할 대상이 없으면 사격 종료
            return
        
        # [7] 재장전
        reload_delay = self._get_reload_delay(unit.unit.unit_type)
        reload_evt = SimulationEvent(
            time=current_time + reload_delay,
            actor=unit,
            action=Action.FIRE.value,
            details={"targets": [reload_target]}
        )
        event_queue.schedule(reload_evt)
                

    # 직사화기 재장전 함수
    def _get_reload_delay(self, utype: UnitType) -> float:
        if utype == UnitType.TANK:
            return float(np.random.triangular(6.0, 8.0, 12.0))
        if utype == UnitType.INFANTRY:
            return float(np.random.uniform(2.0, 3.0))
        if utype == UnitType.ANTI_TANK:
            return float(np.random.uniform(5.0, 7.0))
        # Command post는 어떻게 처리?
        return float(np.random.uniform(2.0, 3.0))
        

    def _process_rifle_damage(self, unit: CombatUnit, target: CombatUnit, distance: float):
        """소총류 피해 처리 (피해 타입별로 상태 변경)"""
        damage_type = self.prob_system.determine_rifle_damage(
            distance,
            target.get_target_state()
        )
        # 피해량 계산 및 적용
        damage = self.DAMAGE_VALUES['rifle'][damage_type]
        old_health = target.unit.health
        target.unit.health = max(0, old_health - damage)
        print(f"Rifle damage: {unit.unit.id} -> {target.unit.id}, Type: {damage_type}, Damage: {damage}, Health: {old_health} -> {target.unit.health}")
        
        if target.unit.health <= 0:
            target.state = UnitState.K_KILL
            print(f"Unit {target.unit.id} KILLED by rifle fire")
        elif damage_type == DamageType.FATAL:
            target.state = UnitState.K_KILL
            print(f"Unit {target.unit.id} KILLED by fatal rifle damage")
        elif damage_type == DamageType.CRITICAL:
            target.state = UnitState.MF_KILL
        elif damage_type == DamageType.SERIOUS:
            target.state = UnitState.F_KILL
        elif damage_type == DamageType.MINOR:
            target.state = UnitState.M_KILL

    def _process_tank_damage(self, unit: CombatUnit, target: CombatUnit):
        """전차류 피해 처리 (피해 타입별로 상태 변경)"""
        damage_type = self.prob_system.determine_tank_damage(
            target.get_target_state()
        )
        # 피해량 계산 및 적용
        damage = self.DAMAGE_VALUES['tank'][damage_type]
        old_health = target.unit.health
        target.unit.health = max(0, old_health - damage)
        print(f"Tank damage: {unit.unit.id} -> {target.unit.id}, Type: {damage_type}, Damage: {damage}, Health: {old_health} -> {target.unit.health}")
        
        if target.unit.health <= 0:
            target.state = UnitState.K_KILL
            print(f"Unit {target.unit.id} KILLED by tank fire")
        elif damage_type == TankDamageType.COMPLETE:
            target.state = UnitState.K_KILL
            print(f"Unit {target.unit.id} KILLED by complete tank damage")
        elif damage_type == TankDamageType.FIREPOWER:
            target.state = UnitState.F_KILL
        elif damage_type == TankDamageType.MOBILITY:
            target.state = UnitState.M_KILL
        elif damage_type == TankDamageType.TURRET:
            target.state = UnitState.MF_KILL

    # 사거리 constraint (현재 사용 안되고 있는 함수)
    def is_in_range(self, unit: CombatUnit, target: CombatUnit) -> bool:
        """무기별 사거리 내에 있는지 판정"""
        distance = self._calculate_distance(unit.unit.position, target.unit.position)
        return distance <= self.WEAPON_RANGES[unit.unit.unit_type]

    # [1] 명중확률(P_h) 불러오기 -> _direct_fire 내에 구현됨.
    def calculate_hit_probability(self, unit: CombatUnit, target: CombatUnit) -> float:
        """명중 확률 계산 (무기/거리/상태 반영)"""
        distance = self._calculate_distance(unit.unit.position, target.unit.position)
        target_state = target.get_target_state()
        weapon_type = "rifle" if unit.unit.unit_type == UnitType.INFANTRY else "tank"
        return self.prob_system.get_hit_probability(weapon_type, distance, target_state)

    # 체력 감소 처리 함수
    def process_damage(self, unit: CombatUnit, target: CombatUnit) -> float:
        """피해량 계산 및 반환 (실제 체력 감소는 외부에서)"""
        distance = self._calculate_distance(unit.unit.position, target.unit.position)
        target_state = target.get_target_state()
        if unit.unit.unit_type == UnitType.INFANTRY:
            damage_type = self.prob_system.determine_rifle_damage(distance, target_state)
            return self.DAMAGE_VALUES['rifle'][damage_type]
        else:
            damage_type = self.prob_system.determine_tank_damage(target_state)
            return self.DAMAGE_VALUES['tank'][damage_type] 


# 기동
    def maneuver(self,
                 unit: CombatUnit,
                 goal: Tuple[float, float],
                 event_queue: EventQueue,
                 current_time: float,
                 terrain: TerrainSystem,
                 all_units: List[CombatUnit]):
        """
        1) Bresenham 경로로 A→B 직선상의 픽셀(path) 생성
        2) terrain.get_terrain_effects() 로 속도 계수 얻기
        3) 1픽셀 이동시간 계산 → 누적 시간 t 에 더하기
        4) 이동 중 detect() 로 적 조우 확인 → 있으면 FIRE 이벤트 예약 후 리턴
        5) 없으면 MOVE 이벤트 예약
        """
        # 목적지가 다 겹칠 수 있으니, -10~+10 uniform dist 적용해서 더해서 좀 흐트러지게 설정.
        # 1) 시작·목표 좌표 추출 -> 목표에 -10~+10 uniform dist 난수 적용
        '''픽셀 scale할 때 난수도 조정 필요'''
        sx, sy = map(int, unit.unit.position)
        base_gx, base_gy = map(int, goal) # command에서 이동 위치 좌표 받아와야함.
        
        # 난수 생성
        jitter_x = np.random.uniform(-10, 10)
        jitter_y = np.random.uniform(-10, 10)
        gx = int(base_gx + jitter_x)
        gy = int(base_gy + jitter_y)
        # 난수 적용 시 맵 경계 밖으로 나가지 않도록 클램핑
        gx = max(0, min(gx, terrain.dem_width - 1))
        gx = max(0, min(gx, terrain.dem_width - 1))


        # Bresenham 알고리즘: path 계산 -> 다시 확인. 잘 round가 되는지.
        path = []
        dx, dy = abs(gx - sx), abs(gy - sy)
        sx_step = 1 if gx > sx else -1
        sy_step = 1 if gy > sy else -1
        err = dx - dy
        x, y = sx, sy
        while True:
            path.append((x, y))
            if x == gx and y == gy:
                break
            e2 = err * 2
            if e2 > -dy:
                err -= dy; x += sx_step
            if e2 <  dx:
                err += dx; y += sy_step

        # 2) 기본속도 조회
        base_speed = MOVEMENT_SPEED[unit.unit.unit_type]
        t = current_time

        # 3~5) path 순회
        for nx, ny in path:
            # terrain 효과
            eff: TerrainEffects = terrain.get_terrain_effects(nx, ny, unit.unit.unit_type.name)
            speed_mod = eff.movement_speed
            if base_speed * speed_mod <= 0:
                continue  # COMMAND_POST 등 고정형은 건너뛰기

            # 3) 이동시간 계산
            t += 1.0 / (base_speed * speed_mod)

            # 4) 이동 중 적 조우 검사
            self.detect(unit, all_units, terrain)
            if unit.target_list:
                # 바로 FIRE 이벤트 예약
                fire_evt = SimulationEvent(
                    time=t,
                    actor=unit,
                    action=Action.FIRE.value,
                    details={"targets": list(unit.target_list)}
                )
                event_queue.schedule(fire_evt)
                return # 남은 이동 경로는 모두 취소

            # 5) MOVE 이벤트 예약
            move_evt = SimulationEvent(
                time=t,
                actor=unit,
                action=Action.MANEUVER.value,
                details={"new_position": (nx, ny)}
            )
            event_queue.schedule(move_evt)
        # 목표 도달 시 종료

    @staticmethod
    def _calculate_distance(pos1: Tuple[float, float], pos2: Tuple[float, float]) -> float:
        """두 위치(픽셀 좌표) 간 유클리드 거리 계산"""
        return np.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)

    def estimate_friendly_fire(self,
                                 impact_point: Tuple[float, float],
                                 all_units: List[CombatUnit],
                                 firing_team: str) -> float:
        """
        주어진 탄착 지점 주변 치사 반경 내 아군 유닛이 받을
        피해 기대값(또는 확률)을 계산하여 반환합니다.
        """
        # 픽셀→실제 거리 환산 적용
        R_L = self.ARTILLERY_LETHAL_RADIUS * self.distance_rescale
        risk = 0.0
        for cu in all_units:
            # 같은 팀 유닛만 계산
            if cu.unit.team == firing_team:
                # 치사 반경 내에 있으면 확률 가중치 누적
                d_pix = self._calculate_distance(impact_point, cu.unit.position)
                d = d_pix * self.distance_rescale
                if d <= R_L:
                    p = math.exp(- (d ** 2) / (2 * (R_L ** 2)))
                    risk += p
        return risk
# User Stories - PM Review (Task 17)

## Problem Statement
Current buddy_service.py is a 1827-line god object that violates single responsibility principle, making it difficult to maintain, test, and scale. This creates technical debt and slows down feature development.

## Success Metrics
- Reduce buddy_service.py from 1827 to <100 lines
- Achieve >90% test coverage for each new service
- Maintain 100% backward compatibility
- Reduce average PR review time by 30%
- Zero production incidents during migration

## RICE Prioritization

### High Priority (Score: 8-10)
**US-17.1: BuddyBaseService (Foundation)**
- **Reach**: 10 (affects all other services)
- **Impact**: 8 (enables all other refactoring)
- **Confidence**: 9 (straightforward extraction)
- **Effort**: 3 (2-3 days)
- **RICE Score**: 10×8×9/3 = 240

**US-17.2: BuddyCareService**
- **Reach**: 8 (core user feature)
- **Impact**: 7 (improves maintainability)
- **Confidence**: 8 (well-defined methods)
- **Effort**: 4 (3-4 days)
- **RICE Score**: 8×7×8/4 = 112

**US-17.3: BuddyTrainingService**
- **Reach**: 7 (frequent user feature)
- **Impact**: 7 (improves maintainability)
- **Confidence**: 8 (well-defined methods)
- **Effort**: 3 (2-3 days)
- **RICE Score**: 7×7×8/3 = 131

**US-17.4: BuddyCoinsService**
- **Reach**: 9 (affects shop and consultations)
- **Impact**: 8 (critical for monetization)
- **Confidence**: 9 (simple methods)
- **Effort**: 2 (1-2 days)
- **RICE Score**: 9×8×9/2 = 324

**US-17.8: Router Refactoring**
- **Reach**: 10 (all API endpoints)
- **Impact**: 9 (completes migration)
- **Confidence**: 7 (complex integration)
- **Effort**: 5 (4-5 days)
- **RICE Score**: 10×9×7/5 = 126

### Medium Priority (Score: 4-7)
**US-17.5: BuddyShopService**
- **Reach**: 6 (shop users only)
- **Impact**: 6 (moderate complexity)
- **Confidence**: 8 (depends on coins service)
- **Effort**: 4 (3-4 days)
- **RICE Score**: 6×6×8/4 = 72

**US-17.6: BuddyMinigameService**
- **Reach**: 5 (gaming users only)
- **Impact**: 5 (simple feature)
- **Confidence**: 9 (only 2 methods)
- **Effort**: 2 (1-2 days)
- **RICE Score**: 5×5×9/2 = 112

**US-17.7: BuddyConsultationService**
- **Reach**: 4 (consultation users only)
- **Impact**: 6 (moderate complexity)
- **Confidence**: 8 (depends on coins service)
- **Effort**: 3 (2-3 days)
- **RICE Score**: 4×6×8/3 = 64

### Low Priority (Score: 1-3)
**US-17.9: Cleanup Old Service**
- **Reach**: 2 (internal cleanup)
- **Impact**: 3 (reduces tech debt)
- **Confidence**: 9 (simple deletion)
- **Effort**: 1 (few hours)
- **RICE Score**: 2×3×9/1 = 54

## Dependencies & Execution Order
1. **Wave 1**: US-17.1 (BuddyBaseService) - Foundation
2. **Wave 2**: US-17.2, US-17.3, US-17.4, US-17.6 (parallel, depend on 17.1)
3. **Wave 3**: US-17.5, US-17.7 (depend on 17.4)
4. **Wave 4**: US-17.8 (Router refactoring)
5. **Wave 5**: US-17.9 (Cleanup)

## Effort Estimation (with 20% buffer)
- Base effort: 27 days
- With 20% buffer: 33 days
- Recommended timeline: 7 weeks (35 days)

## Risk Mitigation
- Feature flags for gradual rollout
- Comprehensive integration tests
- Database migration scripts
- Rollback procedures documented

## Acceptance Criteria (Global)
- All existing tests pass
- API contracts unchanged
- Performance benchmarks maintained
- Code coverage >90% per service
- Documentation updated
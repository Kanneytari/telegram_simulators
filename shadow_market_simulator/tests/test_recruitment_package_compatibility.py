from app.recruitment import (
    CHANNELS as LegacyChannels,
    DURATION_OPTIONS as LegacyDurationOptions,
    RETAIL_STARTING_DEPOSIT_CAP as LegacyRetailStartingDepositCap,
    ROLE_TITLES as LegacyRoleTitles,
    VOLUME_OPTIONS as LegacyVolumeOptions,
    RecruitmentChannel as LegacyRecruitmentChannel,
    RecruitmentService as LegacyRecruitmentService,
)
from app.staff.recruitment import (
    CHANNELS,
    DURATION_OPTIONS,
    RETAIL_STARTING_DEPOSIT_CAP,
    ROLE_TITLES,
    VOLUME_OPTIONS,
    RecruitmentChannel,
    RecruitmentService,
)


def test_recruitment_legacy_module_is_a_thin_facade() -> None:
    assert LegacyRecruitmentService is RecruitmentService
    assert LegacyRecruitmentChannel is RecruitmentChannel
    assert LegacyChannels is CHANNELS
    assert LegacyDurationOptions is DURATION_OPTIONS
    assert LegacyRoleTitles is ROLE_TITLES
    assert LegacyVolumeOptions is VOLUME_OPTIONS
    assert LegacyRetailStartingDepositCap == RETAIL_STARTING_DEPOSIT_CAP

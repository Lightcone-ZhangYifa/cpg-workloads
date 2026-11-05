#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <cstdint>
#include <cstring>
#include <vector>
static bool deliberate_failure=false;
struct Source { virtual ~Source()=default; virtual int read(int)=0; };
struct MockSource : Source { MOCK_METHOD(int,read,(int),(override)); };
TEST(Consumer, Arithmetic) { EXPECT_EQ(std::uint64_t{1}<<40, 1099511627776ULL); }
TEST(Consumer, MatchersAndMock) {
    MockSource source; EXPECT_CALL(source,read(7)).WillOnce(::testing::Return(42));
    EXPECT_EQ(source.read(7),42); EXPECT_THAT(std::vector<int>({2,3,5}),::testing::ElementsAre(2,3,5));
}
TEST(Consumer, FailureContract) { EXPECT_FALSE(deliberate_failure); }
int main(int argc,char **argv) {
    for(int i=1;i<argc;i++) if(!std::strcmp(argv[i],"--cpg-fail")) deliberate_failure=true;
    ::testing::InitGoogleTest(&argc,argv); return RUN_ALL_TESTS();
}

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>
static bool deliberate_failure = false;
struct Source { virtual ~Source() = default; virtual int read(int) = 0; };
struct MockSource : Source { MOCK_METHOD(int, read, (int), (override)); };
TEST(CPGConsumer, IntegerArithmetic) { EXPECT_EQ(std::uint64_t{1} << 40, 1099511627776ULL); }
TEST(CPGConsumer, MatchersAndMock) {
    MockSource source;
    EXPECT_CALL(source, read(7)).WillOnce(::testing::Return(42));
    EXPECT_EQ(source.read(7), 42);
    EXPECT_THAT(std::vector<int>({2, 3, 5}), ::testing::ElementsAre(2, 3, 5));
}
TEST(CPGConsumer, StringEquality) { EXPECT_EQ(std::string("hello") + " UTF-8 \xe4\xb8\xad", "hello UTF-8 \xe4\xb8\xad"); }
TEST(CPGConsumer, ExceptionContract) { EXPECT_THROW(throw std::runtime_error("expected"), std::runtime_error); }
TEST(CPGConsumer, FailureContract) { EXPECT_FALSE(deliberate_failure); }
int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) if (!std::strcmp(argv[i], "--cpg-fail")) deliberate_failure = true;
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}

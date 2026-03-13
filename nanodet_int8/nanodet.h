//
// Create by RangiLyu
// 2020 / 10 / 2
//

#ifndef NANODET_H
#define NANODET_H

#include <opencv2/core/core.hpp>
#include <net.h>

typedef struct HeadInfo
{
    std::string cls_layer;
    std::string dis_layer;
    int stride;
};

struct CenterPrior
{
    int x;
    int y;
    int stride;
};

typedef struct BoxInfo
{
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
    int label;
} BoxInfo;

class NanoDet
{
public:
    NanoDet(const char* param, const char* bin, bool useGPU);

    ~NanoDet();

    static NanoDet* detector;
    ncnn::Net* Net;
    static bool hasGPU;
    // modify these parameters to the same with your config if you want to use your own model
    int input_size[2] = {320, 320}; // input height and width (320 for RPi4 speed, 640 for accuracy)
    int num_class = 1; // number of classes. 80 for COCO
    int reg_max = 7; // `reg_max` set in the training config. Default: 7.
    std::vector<int> strides = { 8, 16, 32, 64 }; // strides of the multi-level feature.

    std::vector<BoxInfo> detect(cv::Mat image, float score_threshold, float nms_threshold);

    void loadCalibration(const char* calib_path);
    bool estimatePose(const BoxInfo& bbox, float& x, float& y, float& z);

    float fx = 0, fy = 0, cx = 0, cy = 0;
    bool has_calibration = false;
    float frisbee_diameter = 0.30f; // 30cm real-world diameter
    float depth_scale = 1.10f;     // Correction factor (tuned: 0.85 * 1.75/1.35)

    std::vector<std::string> labels{ "frisbee" };
private:
    void preprocess(cv::Mat& image, ncnn::Mat& in);
    void decode_infer(ncnn::Mat& feats, std::vector<CenterPrior>& center_priors, float threshold, std::vector<std::vector<BoxInfo>>& results);
    BoxInfo disPred2Bbox(const float*& dfl_det, int label, float score, int x, int y, int stride);
    static void nms(std::vector<BoxInfo>& result, float nms_threshold);

};


#endif //NANODET_H

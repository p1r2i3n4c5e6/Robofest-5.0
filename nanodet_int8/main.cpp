#include <opencv2/core/core.hpp>
#include <opencv2/highgui/highgui.hpp>
#include <opencv2/imgproc/imgproc.hpp>
#include <iostream>
#include <net.h>
#include "nanodet.h"
#include <benchmark.h>

struct object_rect {
    int x;
    int y;
    int width;
    int height;
};

int resize_uniform(cv::Mat& src, cv::Mat& dst, cv::Size dst_size, object_rect& effect_area)
{
    int w = src.cols;
    int h = src.rows;
    int dst_w = dst_size.width;
    int dst_h = dst_size.height;
    dst = cv::Mat(cv::Size(dst_w, dst_h), CV_8UC3, cv::Scalar(0));

    float ratio_src = w * 1.0 / h;
    float ratio_dst = dst_w * 1.0 / dst_h;

    int tmp_w = 0;
    int tmp_h = 0;
    if (ratio_src > ratio_dst) {
        tmp_w = dst_w;
        tmp_h = floor((dst_w * 1.0 / w) * h);
    }
    else if (ratio_src < ratio_dst) {
        tmp_h = dst_h;
        tmp_w = floor((dst_h * 1.0 / h) * w);
    }
    else {
        cv::resize(src, dst, dst_size);
        effect_area.x = 0;
        effect_area.y = 0;
        effect_area.width = dst_w;
        effect_area.height = dst_h;
        return 0;
    }

    cv::Mat tmp;
    cv::resize(src, tmp, cv::Size(tmp_w, tmp_h));

    if (tmp_w != dst_w) {
        int index_w = floor((dst_w - tmp_w) / 2.0);
        for (int i = 0; i < dst_h; i++) {
            memcpy(dst.data + i * dst_w * 3 + index_w * 3, tmp.data + i * tmp_w * 3, tmp_w * 3);
        }
        effect_area.x = index_w;
        effect_area.y = 0;
        effect_area.width = tmp_w;
        effect_area.height = tmp_h;
    }
    else if (tmp_h != dst_h) {
        int index_h = floor((dst_h - tmp_h) / 2.0);
        memcpy(dst.data + index_h * dst_w * 3, tmp.data, tmp_w * tmp_h * 3);
        effect_area.x = 0;
        effect_area.y = index_h;
        effect_area.width = tmp_w;
        effect_area.height = tmp_h;
    }
    else {
        printf("error\n");
    }
    return 0;
}

const int color_list[80][3] =
{
    {216 , 82 , 24}, {236 ,176 , 31}, {125 , 46 ,141}, {118 ,171 , 47},
    { 76 ,189 ,237}, {238 , 19 , 46}, { 76 , 76 , 76}, {153 ,153 ,153},
    {255 ,  0 ,  0}, {255 ,127 ,  0}, {190 ,190 ,  0}, {  0 ,255 ,  0},
    {  0 ,  0 ,255}, {170 ,  0 ,255}, { 84 , 84 ,  0}, { 84 ,170 ,  0},
    { 84 ,255 ,  0}, {170 , 84 ,  0}, {170 ,170 ,  0}, {170 ,255 ,  0},
    {255 , 84 ,  0}, {255 ,170 ,  0}, {255 ,255 ,  0}, {  0 , 84 ,127},
    {  0 ,170 ,127}, {  0 ,255 ,127}, { 84 ,  0 ,127}, { 84 , 84 ,127},
    { 84 ,170 ,127}, { 84 ,255 ,127}, {170 ,  0 ,127}, {170 , 84 ,127},
    {170 ,170 ,127}, {170 ,255 ,127}, {255 ,  0 ,127}, {255 , 84 ,127},
    {255 ,170 ,127}, {255 ,255 ,127}, {  0 , 84 ,255}, {  0 ,170 ,255},
    {  0 ,255 ,255}, { 84 ,  0 ,255}, { 84 , 84 ,255}, { 84 ,170 ,255},
    { 84 ,255 ,255}, {170 ,  0 ,255}, {170 , 84 ,255}, {170 ,170 ,255},
    {170 ,255 ,255}, {255 ,  0 ,255}, {255 , 84 ,255}, {255 ,170 ,255},
    { 42 ,  0 ,  0}, { 84 ,  0 ,  0}, {127 ,  0 ,  0}, {170 ,  0 ,  0},
    {212 ,  0 ,  0}, {255 ,  0 ,  0}, {  0 , 42 ,  0}, {  0 , 84 ,  0},
    {  0 ,127 ,  0}, {  0 ,170 ,  0}, {  0 ,212 ,  0}, {  0 ,255 ,  0},
    {  0 ,  0 , 42}, {  0 ,  0 , 84}, {  0 ,  0 ,127}, {  0 ,  0 ,170},
    {  0 ,  0 ,212}, {  0 ,  0 ,255}, { 36 , 36 , 36}, { 72 , 72 , 72},
    {109 ,109 ,109}, {145 ,145 ,145}, {182 ,182 ,182}, {218 ,218 ,218},
    {  0 ,113 ,188}, { 80 ,182 ,188}, {127 ,127 ,  0},
};

void draw_bboxes(const cv::Mat& bgr, const std::vector<BoxInfo>& bboxes, object_rect effect_roi, float fps = -1, NanoDet* detector = nullptr)
{
    static const char* class_names[] = { "frisbee" };

    cv::Mat image = bgr.clone();
    int src_w = image.cols;
    int src_h = image.rows;
    int dst_w = effect_roi.width;
    int dst_h = effect_roi.height;
    float width_ratio = (float)src_w / (float)dst_w;
    float height_ratio = (float)src_h / (float)dst_h;

    // ── Send grouped AI_COORD for Python's CentroidTracker ──
    if (!bboxes.empty()) {
        std::string frame_output = "AI_COORD:";
        for (size_t i = 0; i < bboxes.size(); i++)
        {
            const BoxInfo& bbox = bboxes[i];
            float x1_orig = (bbox.x1 - effect_roi.x) * width_ratio;
            float y1_orig = (bbox.y1 - effect_roi.y) * height_ratio;
            float x2_orig = (bbox.x2 - effect_roi.x) * width_ratio;
            float y2_orig = (bbox.y2 - effect_roi.y) * height_ratio;
            float center_x = x1_orig + (x2_orig - x1_orig) / 2.0f;
            float center_y = y1_orig + (y2_orig - y1_orig) / 2.0f;
            float w_orig = x2_orig - x1_orig;
            float h_orig = y2_orig - y1_orig;

            frame_output += std::to_string((int)center_x) + "," + std::to_string((int)center_y) + "," +
                            std::to_string((int)w_orig) + "," + std::to_string((int)h_orig);
            if (i < bboxes.size() - 1) frame_output += "|";
        }
        printf("%s\n", frame_output.c_str());
        fflush(stdout);
    }

    for (size_t i = 0; i < bboxes.size(); i++)
    {
        const BoxInfo& bbox = bboxes[i];
        cv::Scalar color = cv::Scalar(0, 0, 255); // Bright RED (BGR)

        float x1_orig = (bbox.x1 - effect_roi.x) * width_ratio;
        float y1_orig = (bbox.y1 - effect_roi.y) * height_ratio;
        float x2_orig = (bbox.x2 - effect_roi.x) * width_ratio;
        float y2_orig = (bbox.y2 - effect_roi.y) * height_ratio;

        cv::rectangle(image, cv::Rect(cv::Point(x1_orig, y1_orig),
                                      cv::Point(x2_orig, y2_orig)), color, 3);

        char text[256];
        sprintf(text, "%s %.1f%%", class_names[bbox.label], bbox.score * 100);

        // --- Pose Estimation ---
        if (detector && detector->has_calibration) {
            float w_orig = x2_orig - x1_orig;
            float h_orig = y2_orig - y1_orig;
            float max_dim = std::max(w_orig, h_orig);
            if (max_dim > 0) {
                float center_x = x1_orig + w_orig / 2.0f;
                float center_y = y1_orig + h_orig / 2.0f;
                
                float z = (detector->fx * detector->frisbee_diameter) / max_dim;
                z *= detector->depth_scale;
                float x_pos = ((center_x - detector->cx) * z) / detector->fx;
                float y_pos = ((center_y - detector->cy) * z) / detector->fy;
                
                sprintf(text, "%s %.1f%% | X:%.2fm Y:%.2fm Z:%.2fm", class_names[bbox.label], bbox.score * 100, x_pos, y_pos, z);
            }
        }

        int baseLine = 0;
        cv::Size label_size = cv::getTextSize(text, cv::FONT_HERSHEY_SIMPLEX, 0.7, 2, &baseLine);

        int x = (bbox.x1 - effect_roi.x) * width_ratio;
        int y = (bbox.y1 - effect_roi.y) * height_ratio - label_size.height - baseLine;
        if (y < 0) y = 0;
        if (x + label_size.width > image.cols) x = image.cols - label_size.width;

        cv::rectangle(image, cv::Rect(cv::Point(x, y), cv::Size(label_size.width, label_size.height + baseLine)),
            color, -1);

        cv::putText(image, text, cv::Point(x, y + label_size.height),
            cv::FONT_HERSHEY_SIMPLEX, 0.7, cv::Scalar(255, 255, 255), 2);
    }

    if (fps > 0)
    {
        char fps_text[64];
        sprintf(fps_text, "FPS: %.1f", fps);
        cv::putText(image, fps_text, cv::Point(10, 30),
            cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(0, 255, 0), 2);
    }

    cv::Mat display;
    cv::resize(image, display, cv::Size(640, 480));
    cv::imshow("NanoDet NCNN - Frisbee Detection", display);
}


int image_demo(NanoDet &detector, const char* imagepath)
{
    std::vector<cv::String> filenames;
    cv::glob(imagepath, filenames, false);
    int height = detector.input_size[0];
    int width = detector.input_size[1];

    for (auto img_name : filenames)
    {
        cv::Mat image = cv::imread(img_name);
        if (image.empty())
        {
            fprintf(stderr, "cv::imread %s failed\n", img_name);
            return -1;
        }
        object_rect effect_roi;
        cv::Mat resized_img;
        resize_uniform(image, resized_img, cv::Size(width, height), effect_roi);
        auto results = detector.detect(resized_img, 0.35, 0.5);
        draw_bboxes(image, results, effect_roi, -1, &detector);
        cv::waitKey(0);

    }
    return 0;
}

#include <mutex>
#include <thread>
#include <atomic>

class CameraScanner {
public:
    CameraScanner(int cam_id) : running(true), is_new_frame(false) {
        // IMX708 requires libcamera — use GStreamer with EXPLICIT BGR conversion
        std::string gst_pipeline = "libcamerasrc ! video/x-raw,width=640,height=480,framerate=30/1 "
                                   "! videoconvert ! video/x-raw,format=BGR ! appsink drop=1";
        printf("[Camera] Trying GStreamer: %s\n", gst_pipeline.c_str());
        fflush(stdout);
        cap.open(gst_pipeline, cv::CAP_GSTREAMER);

        // Fallback to V4L2 if GStreamer fails
        if (!cap.isOpened()) {
            printf("[Camera] GStreamer failed. Trying V4L2...\n");
            fflush(stdout);
            cap.open(cam_id, cv::CAP_V4L2);
            if (cap.isOpened()) {
                cap.set(cv::CAP_PROP_FRAME_WIDTH, 640);
                cap.set(cv::CAP_PROP_FRAME_HEIGHT, 480);
            }
        }

        if (cap.isOpened()) {
            printf("[Camera] Opened successfully!\n");
            fflush(stdout);
            // Grab a few frames to let the sensor warm up
            for (int i = 0; i < 5; i++) cap.read(latest_frame);
            capture_thread = std::thread(&CameraScanner::update, this);
        }
    }

    ~CameraScanner() {
        running = false;
        if (capture_thread.joinable()) {
            capture_thread.join();
        }
        cap.release();
    }

    void update() {
        while (running) {
            cv::Mat frame;
            if (cap.read(frame) && !frame.empty()) {
                std::lock_guard<std::mutex> lock(mtx);
                latest_frame = frame.clone();
                is_new_frame = true;
            }
        }
    }

    bool read(cv::Mat& output) {
        std::lock_guard<std::mutex> lock(mtx);
        if (!latest_frame.empty()) {
            output = latest_frame.clone();
            is_new_frame = false;
            return true;
        }
        return false;
    }

    bool isOpened() const { return cap.isOpened(); }

private:
    cv::VideoCapture cap;
    cv::Mat latest_frame;
    std::mutex mtx;
    std::thread capture_thread;
    std::atomic<bool> running;
    std::atomic<bool> is_new_frame;
};


int webcam_demo(NanoDet& detector, int cam_id)
{
    cv::Mat image;
    CameraScanner scanner(cam_id);
    if (!scanner.isOpened())
    {
        fprintf(stderr, "Error: Cannot open camera %d\n", cam_id);
        return -1;
    }

    int height = detector.input_size[0];
    int width = detector.input_size[1];

    int empty_count = 0;
    while (true)
    {
        bool ret = scanner.read(image);
        if (!ret || image.empty())
        {
            empty_count++;
            if (empty_count > 300) break;
            continue;
        }
        empty_count = 0;

        object_rect effect_roi;
        cv::Mat resized_img;
        resize_uniform(image, resized_img, cv::Size(width, height), effect_roi);

        double start = ncnn::get_current_time();
        auto results = detector.detect(resized_img, 0.35, 0.5);
        double end = ncnn::get_current_time();
        double dt = end - start;
        float fps = (dt > 0) ? 1000.0 / dt : 0;

        draw_bboxes(image, results, effect_roi, fps, &detector);
        if (cv::waitKey(1) == 27) break;
    }
    return 0;
}

int main(int argc, char** argv)
{
    if (argc != 3)
    {
        fprintf(stderr, "usage: %s [mode] [path]. \n For webcam mode=0, path is cam id; \n For image demo, mode=1, path=xxx/xxx/*.jpg\n", argv[0]);
        return -1;
    }
    NanoDet detector = NanoDet("./nanodet.param", "./nanodet.bin", true);
    detector.loadCalibration("./calibration.yml");
    int mode = atoi(argv[1]);
    switch (mode)
    {
    case 0:{
        int cam_id = atoi(argv[2]);
        webcam_demo(detector, cam_id);
        break;
        }
    case 1:{
        const char* images = argv[2];
        image_demo(detector, images);
        break;
        }
    default:{
        fprintf(stderr, "usage: %s [mode] [path]\n", argv[0]);
        break;
        }
    }
}
